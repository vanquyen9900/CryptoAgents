"""Portfolio-style A/B benchmark for the GOOGL Regime Analyst.

This benchmark is intentionally conservative with API spend:

- 30 non-overlapping 5-session rebalance windows by default.
- Two independent long-only portfolios:
  - baseline: Market Analyst only
  - regime: Market Analyst + Regime/Quantitative Analyst
- Execution happens at the decision session close.
- Daily mark-to-market is recorded through the next 5 sessions.
- Fees and slippage are set to zero by design.
- Checkpointing happens after every agent run so the script can resume.
- A max-cost guard stops before starting a run that would likely exceed budget.

The script does not print API keys and never writes them to checkpoint/report.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency in some envs
    load_dotenv = None

from langchain_community.callbacks.manager import get_openai_callback

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data_5y" / "GOOGL" / "GOOGL_ohlcv.csv"
OUT_DIR = ROOT / "reports" / "regime_portfolio_googl"
CHECKPOINT_PATH = OUT_DIR / "checkpoint.json"
REPORT_PATH = OUT_DIR / "GOOGL_REGIME_PORTFOLIO_30W.md"

BRANCHES = {
    "baseline": {
        "label": "Without Regime",
        "analysts": ["market"],
    },
    "regime": {
        "label": "With Regime",
        "analysts": ["market", "quantitative"],
    },
}

RATING_TO_TARGET = {
    "Buy": 100.0,
    "Overweight": 75.0,
    "Underweight": 25.0,
    "Sell": 0.0,
}

# OpenAI pricing used for local cost guard. Keep as script args so it is easy
# to update if pricing changes.
DEFAULT_INPUT_PRICE_PER_M = 0.20
DEFAULT_OUTPUT_PRICE_PER_M = 1.25


@dataclass
class Portfolio:
    cash: float
    shares: float

    def value(self, close: float) -> float:
        return float(self.cash + self.shares * close)

    def weight(self, close: float) -> float:
        value = self.value(close)
        if value <= 0:
            return 0.0
        return float((self.shares * close) / value)


def load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(ROOT / ".env")
        return

    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_prices() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH, comment="#", skip_blank_lines=True)
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df.dropna(subset=["Date", "Close"]).reset_index(drop=True)
    if len(df) < 40:
        raise ValueError(f"Not enough GOOGL rows in {DATA_PATH}")
    return df


def select_schedule(df: pd.DataFrame, weeks: int) -> list[dict[str, Any]]:
    """Pick the most recent non-overlapping 5-session windows."""
    last_decision_idx = len(df) - 6  # needs idx + 5 as the exit close
    indices = list(range(last_decision_idx, -1, -5))[:weeks]
    indices.reverse()
    schedule = []
    for idx in indices:
        exit_idx = idx + 5
        schedule.append(
            {
                "date": str(df.loc[idx, "Date"]),
                "entry_idx": int(idx),
                "exit_idx": int(exit_idx),
                "exit_date": str(df.loc[exit_idx, "Date"]),
                "entry_close": float(df.loc[idx, "Close"]),
                "exit_close": float(df.loc[exit_idx, "Close"]),
            }
        )
    return schedule


def empty_checkpoint(args: argparse.Namespace, schedule: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "meta": {
            "ticker": "GOOGL",
            "weeks_requested": args.weeks,
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "max_cost_usd": args.max_cost,
            "input_price_per_m": args.input_price_per_m,
            "output_price_per_m": args.output_price_per_m,
            "initial_capital": args.initial_capital,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "schedule": schedule,
        "decisions": {"baseline": {}, "regime": {}},
        "errors": [],
        "stopped_reason": None,
    }


def load_checkpoint(args: argparse.Namespace, schedule: list[dict[str, Any]]) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.fresh and CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()
    if CHECKPOINT_PATH.exists():
        with CHECKPOINT_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return empty_checkpoint(args, schedule)


def save_checkpoint(cp: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cp, f, indent=2, ensure_ascii=False)
    tmp.replace(CHECKPOINT_PATH)


def clamp_pct(value: float) -> float:
    return float(max(0.0, min(100.0, value)))


def extract_rating(text: str, signal: str | None = None) -> str:
    if signal in {"Buy", "Overweight", "Hold", "Underweight", "Sell"}:
        return signal
    match = re.search(r"\*\*Rating\*\*\s*:\s*(Buy|Overweight|Hold|Underweight|Sell)", text, re.I)
    if match:
        return match.group(1).title()
    for rating in ["Overweight", "Underweight", "Buy", "Hold", "Sell"]:
        if re.search(rf"\b{rating}\b", text, re.I):
            return rating
    return "Hold"


def extract_target_weight(text: str, rating: str, current_weight_pct: float) -> tuple[float, str]:
    patterns = [
        r"\*\*Target Weight\*\*\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        r"target_weight_pct[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)",
        r"target weight[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*%",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return clamp_pct(float(match.group(1))), "model"

    if rating == "Hold":
        return clamp_pct(current_weight_pct), "fallback_hold_current_weight"
    return clamp_pct(RATING_TO_TARGET.get(rating, current_weight_pct)), "fallback_rating_map"


def portfolio_context(
    branch_label: str,
    date: str,
    close: float,
    portfolio: Portfolio,
    initial_capital: float,
    previous_decision: dict[str, Any] | None,
    last_window_return: float | None,
) -> str:
    value = portfolio.value(close)
    current_weight = portfolio.weight(close) * 100.0
    previous_rating = previous_decision.get("rating") if previous_decision else "None"
    previous_target = previous_decision.get("target_weight_pct") if previous_decision else None
    previous_target_text = "None" if previous_target is None else f"{previous_target:.2f}%"
    last_return_text = "N/A" if last_window_return is None else f"{last_window_return * 100:.2f}%"
    cumulative_return = value / initial_capital - 1.0

    return "\n".join(
        [
            f"Benchmark branch: {branch_label}",
            f"Decision date: {date}; execution price: close = {close:.2f}",
            f"Cash: ${portfolio.cash:,.2f}",
            f"GOOGL shares: {portfolio.shares:,.6f}",
            f"Portfolio value: ${value:,.2f}",
            f"Current GOOGL weight: {current_weight:.2f}%",
            f"Previous rating: {previous_rating}",
            f"Previous target GOOGL weight: {previous_target_text}",
            f"Last 5-session portfolio return: {last_return_text}",
            f"Cumulative portfolio return: {cumulative_return * 100:.2f}%",
            "Benchmark rule: choose a long-only target_weight_pct for GOOGL from 0 to 100 for the next 5 trading sessions.",
            "Cash receives 0% return. No leverage, no shorting, no fees, no slippage.",
        ]
    )


def build_config(args: argparse.Namespace, branch: str, date: str) -> dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(
        {
            "llm_provider": "openai",
            "deep_think_llm": args.model,
            "quick_think_llm": args.model,
            "openai_reasoning_effort": args.reasoning_effort,
            "max_debate_rounds": 1,
            "max_risk_discuss_rounds": 1,
            "checkpoint_enabled": False,
            "output_language": "English",
            "results_dir": str(OUT_DIR / "graph_logs" / branch),
            "data_cache_dir": str(OUT_DIR / "cache"),
            "memory_log_path": str(OUT_DIR / "memory_disabled" / f"{branch}_{date}.md"),
        }
    )
    return cfg


def disable_memory(graph: TradingAgentsGraph) -> None:
    graph.memory_log.get_pending_entries = lambda: []
    graph.memory_log.get_past_context = lambda ticker: ""
    graph.memory_log.store_decision = lambda **kwargs: None
    graph.memory_log.batch_update_with_outcomes = lambda updates: None


def estimate_cost(prompt_tokens: int, completion_tokens: int, args: argparse.Namespace) -> float:
    return (
        prompt_tokens * args.input_price_per_m / 1_000_000
        + completion_tokens * args.output_price_per_m / 1_000_000
    )


def completed_cost(cp: dict[str, Any]) -> float:
    total = 0.0
    for branch in BRANCHES:
        for decision in cp["decisions"][branch].values():
            total += float(decision.get("estimated_cost_usd", 0.0))
    return total


def rolling_avg_cost(cp: dict[str, Any], branch: str | None = None) -> float | None:
    costs = []
    branches = [branch] if branch else list(BRANCHES)
    for b in branches:
        for decision in cp["decisions"][b].values():
            cost = decision.get("estimated_cost_usd")
            if cost is not None:
                costs.append(float(cost))
    if not costs:
        return None
    return float(sum(costs) / len(costs))


def run_agent_once(
    args: argparse.Namespace,
    branch: str,
    schedule_row: dict[str, Any],
    portfolio: Portfolio,
    initial_capital: float,
    previous_decision: dict[str, Any] | None,
    last_window_return: float | None,
) -> dict[str, Any]:
    date = schedule_row["date"]
    close = float(schedule_row["entry_close"])
    current_weight_pct = portfolio.weight(close) * 100.0
    pctx = portfolio_context(
        BRANCHES[branch]["label"],
        date,
        close,
        portfolio,
        initial_capital,
        previous_decision,
        last_window_return,
    )

    cfg = build_config(args, branch, date)
    selected = BRANCHES[branch]["analysts"]

    started = time.time()
    with get_openai_callback() as cb:
        graph = TradingAgentsGraph(selected_analysts=selected, debug=False, config=cfg)
        disable_memory(graph)
        state, signal = graph.propagate(
            "GOOGL",
            date,
            asset_type="stock",
            portfolio_context=pctx,
        )

    elapsed = time.time() - started
    final_decision = state.get("final_trade_decision", "")
    rating = extract_rating(final_decision, signal)
    target_weight, target_source = extract_target_weight(
        final_decision,
        rating,
        current_weight_pct,
    )

    prompt_tokens = int(cb.prompt_tokens)
    completion_tokens = int(cb.completion_tokens)
    cost = estimate_cost(prompt_tokens, completion_tokens, args)

    return {
        "date": date,
        "branch": branch,
        "analysts": selected,
        "rating": rating,
        "target_weight_pct": target_weight,
        "target_weight_source": target_source,
        "signal": signal,
        "final_trade_decision": final_decision,
        "elapsed_sec": round(elapsed, 2),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(cb.total_tokens),
        "successful_requests": int(cb.successful_requests),
        "estimated_cost_usd": cost,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def dry_run_decision(branch: str, schedule_row: dict[str, Any], portfolio: Portfolio) -> dict[str, Any]:
    current_weight = portfolio.weight(float(schedule_row["entry_close"])) * 100.0
    rating = "Hold" if branch == "baseline" else "Overweight"
    target = current_weight if rating == "Hold" else 75.0
    return {
        "date": schedule_row["date"],
        "branch": branch,
        "analysts": BRANCHES[branch]["analysts"],
        "rating": rating,
        "target_weight_pct": target,
        "target_weight_source": "dry_run",
        "signal": rating,
        "final_trade_decision": f"DRY RUN: {rating} / target {target:.2f}%",
        "elapsed_sec": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "successful_requests": 0,
        "estimated_cost_usd": 0.0,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def simulate_branch(
    df: pd.DataFrame,
    schedule: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    initial_capital: float,
) -> dict[str, Any]:
    portfolio = Portfolio(cash=initial_capital, shares=0.0)
    curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    total_turnover = 0.0
    correct = 0
    accuracy_n = 0
    previous_value_at_exit: float | None = None

    for i, row in enumerate(schedule):
        date = row["date"]
        decision = decisions.get(date)
        if decision is None:
            break

        entry_idx = int(row["entry_idx"])
        exit_idx = int(row["exit_idx"])
        entry_close = float(df.loc[entry_idx, "Close"])
        exit_close = float(df.loc[exit_idx, "Close"])

        pre_value = portfolio.value(entry_close)
        prev_weight = portfolio.weight(entry_close)
        target_weight = clamp_pct(float(decision["target_weight_pct"])) / 100.0
        target_value = pre_value * target_weight
        current_value = portfolio.shares * entry_close
        trade_value = target_value - current_value
        portfolio.shares += trade_value / entry_close
        portfolio.cash -= trade_value
        turnover = abs(trade_value) / pre_value if pre_value > 0 else 0.0
        total_turnover += turnover

        if not curve:
            curve.append({"date": date, "value": pre_value})

        for idx in range(entry_idx + 1, exit_idx + 1):
            close = float(df.loc[idx, "Close"])
            curve.append({"date": str(df.loc[idx, "Date"]), "value": portfolio.value(close)})

        asset_return = exit_close / entry_close - 1.0
        delta_weight = target_weight - prev_weight
        if abs(delta_weight) < 0.02:
            is_correct = abs(asset_return) < 0.01
        elif delta_weight > 0:
            is_correct = asset_return > 0
        else:
            is_correct = asset_return < 0
        correct += int(is_correct)
        accuracy_n += 1

        exit_value = portfolio.value(exit_close)
        interval_portfolio_return = (
            None
            if previous_value_at_exit is None
            else exit_value / previous_value_at_exit - 1.0
        )
        previous_value_at_exit = exit_value

        trades.append(
            {
                "date": date,
                "exit_date": row["exit_date"],
                "entry_close": entry_close,
                "exit_close": exit_close,
                "rating": decision["rating"],
                "prev_weight_pct": prev_weight * 100.0,
                "target_weight_pct": target_weight * 100.0,
                "target_weight_source": decision.get("target_weight_source"),
                "trade_value": trade_value,
                "turnover": turnover,
                "asset_return": asset_return,
                "is_correct": bool(is_correct),
                "portfolio_value_entry": pre_value,
                "portfolio_value_exit": exit_value,
                "interval_portfolio_return": interval_portfolio_return,
            }
        )

    return {
        "curve": curve,
        "trades": trades,
        "total_turnover": total_turnover,
        "accuracy": correct / accuracy_n if accuracy_n else None,
        "accuracy_n": accuracy_n,
        "accuracy_correct": correct,
    }


def simulate_buy_hold(
    df: pd.DataFrame,
    schedule: list[dict[str, Any]],
    initial_capital: float,
    periods: int,
) -> list[dict[str, Any]]:
    if periods <= 0:
        return []
    first = schedule[0]
    last = schedule[periods - 1]
    start_idx = int(first["entry_idx"])
    end_idx = int(last["exit_idx"])
    start_close = float(df.loc[start_idx, "Close"])
    shares = initial_capital / start_close
    return [
        {"date": str(df.loc[idx, "Date"]), "value": shares * float(df.loc[idx, "Close"])}
        for idx in range(start_idx, end_idx + 1)
    ]


def max_drawdown(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    peaks = np.maximum.accumulate(values)
    drawdowns = values / peaks - 1.0
    return float(np.min(drawdowns))


def metrics_from_curve(curve: list[dict[str, Any]], initial_capital: float) -> dict[str, float]:
    if len(curve) < 2:
        return {
            "cumulative_return": float("nan"),
            "annualized_return": float("nan"),
            "sharpe": float("nan"),
            "sortino": float("nan"),
            "max_drawdown": float("nan"),
            "calmar": float("nan"),
            "volatility": float("nan"),
            "days": 0,
        }

    values = np.array([float(p["value"]) for p in curve], dtype=float)
    returns = values[1:] / values[:-1] - 1.0
    cumulative = values[-1] / values[0] - 1.0
    days = len(returns)
    annualized = (1.0 + cumulative) ** (252.0 / days) - 1.0 if cumulative > -1 else -1.0
    ret_std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    volatility = ret_std * math.sqrt(252.0)
    sharpe = float(np.mean(returns) / ret_std * math.sqrt(252.0)) if ret_std > 0 else float("nan")
    downside = returns[returns < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = (
        float(np.mean(returns) / downside_std * math.sqrt(252.0))
        if downside_std > 0
        else float("nan")
    )
    mdd = max_drawdown(values)
    calmar = annualized / abs(mdd) if mdd < 0 else float("nan")
    return {
        "cumulative_return": float(cumulative),
        "annualized_return": float(annualized),
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": float(calmar),
        "volatility": float(volatility),
        "days": int(days),
    }


def pct(x: float | None) -> str:
    if x is None or not np.isfinite(x):
        return "N/A"
    return f"{x * 100:.2f}%"


def num(x: float | None) -> str:
    if x is None or not np.isfinite(x):
        return "N/A"
    return f"{x:.3f}"


def money(x: float | None) -> str:
    if x is None or not np.isfinite(x):
        return "N/A"
    return f"${x:.4f}"


def build_report(
    args: argparse.Namespace,
    cp: dict[str, Any],
    df: pd.DataFrame,
    schedule: list[dict[str, Any]],
) -> str:
    complete_schedule = [
        row
        for row in schedule
        if row["date"] in cp["decisions"]["baseline"]
        and row["date"] in cp["decisions"]["regime"]
    ]
    periods = len(complete_schedule)

    baseline_sim = simulate_branch(
        df,
        complete_schedule,
        cp["decisions"]["baseline"],
        args.initial_capital,
    )
    regime_sim = simulate_branch(
        df,
        complete_schedule,
        cp["decisions"]["regime"],
        args.initial_capital,
    )
    buy_hold_curve = simulate_buy_hold(df, complete_schedule, args.initial_capital, periods)

    baseline_metrics = metrics_from_curve(baseline_sim["curve"], args.initial_capital)
    regime_metrics = metrics_from_curve(regime_sim["curve"], args.initial_capital)
    bh_metrics = metrics_from_curve(buy_hold_curve, args.initial_capital)

    token_summary = {}
    for branch in BRANCHES:
        items = list(cp["decisions"][branch].values())
        token_summary[branch] = {
            "runs": len(items),
            "prompt_tokens": sum(int(x.get("prompt_tokens", 0)) for x in items),
            "completion_tokens": sum(int(x.get("completion_tokens", 0)) for x in items),
            "total_tokens": sum(int(x.get("total_tokens", 0)) for x in items),
            "runtime_sec": sum(float(x.get("elapsed_sec", 0)) for x in items),
            "estimated_cost_usd": sum(float(x.get("estimated_cost_usd", 0)) for x in items),
        }

    def metric_row(name: str, key: str, is_pct: bool = False) -> str:
        formatter = pct if is_pct else num
        b = baseline_metrics[key]
        r = regime_metrics[key]
        h = bh_metrics[key]
        return f"| {name} | {formatter(b)} | {formatter(r)} | {formatter(h)} |"

    alpha_baseline = baseline_metrics["cumulative_return"] - bh_metrics["cumulative_return"]
    alpha_regime = regime_metrics["cumulative_return"] - bh_metrics["cumulative_return"]
    trading_days = baseline_metrics.get("days", 0)
    ann_turnover_base = (
        baseline_sim["total_turnover"] * 252.0 / trading_days if trading_days else float("nan")
    )
    ann_turnover_regime = (
        regime_sim["total_turnover"] * 252.0 / trading_days if trading_days else float("nan")
    )

    lines = [
        "# GOOGL Regime Portfolio Benchmark",
        "",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Model: `{args.model}`; reasoning effort: `{args.reasoning_effort}`",
        f"- Completed paired windows: {periods}/{args.weeks}",
        f"- Rebalance rule: every 5 trading sessions, execute at decision-day close.",
        "- Portfolios: long-only GOOGL + cash, no leverage/shorting.",
        "- Fees/slippage: intentionally set to 0.",
        "- Branches: baseline = Market Analyst only; regime = Market Analyst + Regime Analyst.",
        f"- Stopped reason: {cp.get('stopped_reason') or 'completed/none'}",
        "",
        "## Performance metrics",
        "",
        "| Metric | Without Regime | With Regime | Buy & Hold |",
        "|---|---:|---:|---:|",
        metric_row("Cumulative return", "cumulative_return", True),
        metric_row("Annualized return", "annualized_return", True),
        metric_row("Sharpe", "sharpe"),
        metric_row("Sortino", "sortino"),
        metric_row("Maximum drawdown", "max_drawdown", True),
        metric_row("Calmar", "calmar"),
        metric_row("Volatility", "volatility", True),
        f"| Alpha vs Buy & Hold | {pct(alpha_baseline)} | {pct(alpha_regime)} | 0.00% |",
        f"| Total turnover | {pct(baseline_sim['total_turnover'])} | {pct(regime_sim['total_turnover'])} | 0.00% |",
        f"| Annualized turnover | {pct(ann_turnover_base)} | {pct(ann_turnover_regime)} | 0.00% |",
        "| Fees | $0.0000 | $0.0000 | $0.0000 |",
        (
            f"| Accuracy | {baseline_sim['accuracy_correct']}/{baseline_sim['accuracy_n']} "
            f"({pct(baseline_sim['accuracy'])}) | "
            f"{regime_sim['accuracy_correct']}/{regime_sim['accuracy_n']} "
            f"({pct(regime_sim['accuracy'])}) | N/A |"
        ),
        "",
        "## Token, runtime, estimated API cost",
        "",
        "| Branch | Runs | Input tokens | Output tokens | Total tokens | Runtime | Est. cost |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for branch, label in [("baseline", "Without Regime"), ("regime", "With Regime")]:
        s = token_summary[branch]
        lines.append(
            f"| {label} | {s['runs']} | {s['prompt_tokens']:,} | "
            f"{s['completion_tokens']:,} | {s['total_tokens']:,} | "
            f"{s['runtime_sec'] / 60:.1f} min | {money(s['estimated_cost_usd'])} |"
        )
    total_cost = sum(s["estimated_cost_usd"] for s in token_summary.values())
    total_tokens = sum(s["total_tokens"] for s in token_summary.values())
    total_runtime = sum(s["runtime_sec"] for s in token_summary.values())
    lines.extend(
        [
            f"| **Total** | {sum(s['runs'] for s in token_summary.values())} |  |  | "
            f"{total_tokens:,} | {total_runtime / 60:.1f} min | {money(total_cost)} |",
            "",
            "## Rebalance decisions",
            "",
            "| Date | Exit date | Without Regime | Target | With Regime | Target | GOOGL 5-session return |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in complete_schedule:
        date = row["date"]
        b = cp["decisions"]["baseline"][date]
        r = cp["decisions"]["regime"][date]
        asset_ret = float(row["exit_close"]) / float(row["entry_close"]) - 1.0
        lines.append(
            f"| {date} | {row['exit_date']} | {b['rating']} | "
            f"{float(b['target_weight_pct']):.1f}% | {r['rating']} | "
            f"{float(r['target_weight_pct']):.1f}% | {pct(asset_ret)} |"
        )

    if cp.get("errors"):
        lines.extend(["", "## Errors", ""])
        for err in cp["errors"]:
            lines.append(f"- {err}")

    return "\n".join(lines) + "\n"


def write_report(args: argparse.Namespace, cp: dict[str, Any], df: pd.DataFrame, schedule: list[dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report(args, cp, df, schedule)
    REPORT_PATH.write_text(report, encoding="utf-8")


def replay_portfolios_for_context(
    df: pd.DataFrame,
    schedule: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    initial_capital: float,
) -> tuple[Portfolio, dict[str, Any] | None, float | None]:
    """Replay completed decisions to get portfolio state before the next run."""
    portfolio = Portfolio(cash=initial_capital, shares=0.0)
    previous_decision = None
    last_window_return = None
    previous_exit_value = None

    for row in schedule:
        decision = decisions.get(row["date"])
        if decision is None:
            break
        entry_idx = int(row["entry_idx"])
        exit_idx = int(row["exit_idx"])
        entry_close = float(df.loc[entry_idx, "Close"])
        pre_value = portfolio.value(entry_close)
        target_weight = clamp_pct(float(decision["target_weight_pct"])) / 100.0
        target_value = pre_value * target_weight
        current_value = portfolio.shares * entry_close
        trade_value = target_value - current_value
        portfolio.shares += trade_value / entry_close
        portfolio.cash -= trade_value
        exit_close = float(df.loc[exit_idx, "Close"])
        exit_value = portfolio.value(exit_close)
        last_window_return = None if previous_exit_value is None else exit_value / previous_exit_value - 1.0
        previous_exit_value = exit_value
        previous_decision = decision

    return portfolio, previous_decision, last_window_return


def run_benchmark(args: argparse.Namespace) -> int:
    load_env()
    if not args.dry_run and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not found in .env/environment", file=sys.stderr)
        return 2

    df = load_prices()
    schedule = select_schedule(df, args.weeks)
    cp = load_checkpoint(args, schedule)
    if not args.dry_run and cp.get("stopped_reason") not in (None, "completed"):
        cp["stopped_reason"] = None

    if args.dry_run:
        for row in schedule[: args.max_pairs or len(schedule)]:
            for branch in BRANCHES:
                if row["date"] in cp["decisions"][branch]:
                    continue
                portfolio, _, _ = replay_portfolios_for_context(
                    df, schedule, cp["decisions"][branch], args.initial_capital
                )
                cp["decisions"][branch][row["date"]] = dry_run_decision(branch, row, portfolio)
        cp["stopped_reason"] = "dry_run"
        save_checkpoint(cp)
        write_report(args, cp, df, schedule)
        print(json.dumps({"ok": True, "dry_run": True, "report": str(REPORT_PATH)}, indent=2))
        return 0

    pairs_started = 0
    for row in schedule:
        date = row["date"]
        if args.max_pairs is not None and pairs_started >= args.max_pairs:
            cp["stopped_reason"] = f"max_pairs={args.max_pairs}"
            break

        missing = [branch for branch in BRANCHES if date not in cp["decisions"][branch]]
        if not missing:
            continue

        estimated_missing = 0.0
        for branch in missing:
            estimated_missing += rolling_avg_cost(cp, branch) or rolling_avg_cost(cp) or args.initial_run_cost_estimate
        if completed_cost(cp) + estimated_missing > args.max_cost:
            cp["stopped_reason"] = (
                f"budget_guard: completed ${completed_cost(cp):.4f}, "
                f"next estimated ${estimated_missing:.4f}, max ${args.max_cost:.4f}"
            )
            save_checkpoint(cp)
            break

        pairs_started += 1
        for branch in missing:
            current_spend = completed_cost(cp)
            next_estimate = rolling_avg_cost(cp, branch) or rolling_avg_cost(cp) or args.initial_run_cost_estimate
            if current_spend + next_estimate > args.max_cost:
                cp["stopped_reason"] = (
                    f"budget_guard_before_{branch}: completed ${current_spend:.4f}, "
                    f"next estimated ${next_estimate:.4f}, max ${args.max_cost:.4f}"
                )
                save_checkpoint(cp)
                write_report(args, cp, df, schedule)
                return 0

            portfolio, previous_decision, last_window_return = replay_portfolios_for_context(
                df,
                schedule,
                cp["decisions"][branch],
                args.initial_capital,
            )
            try:
                decision = run_agent_once(
                    args,
                    branch,
                    row,
                    portfolio,
                    args.initial_capital,
                    previous_decision,
                    last_window_return,
                )
                cp["decisions"][branch][date] = decision
                save_checkpoint(cp)
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "branch": branch,
                            "date": date,
                            "rating": decision["rating"],
                            "target_weight_pct": decision["target_weight_pct"],
                            "tokens": decision["total_tokens"],
                            "cost_usd": round(decision["estimated_cost_usd"], 4),
                            "elapsed_sec": decision["elapsed_sec"],
                            "total_spend_usd": round(completed_cost(cp), 4),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception as exc:
                err = f"{branch} {date}: {type(exc).__name__}: {exc}"
                cp["errors"].append(err)
                cp["stopped_reason"] = "error"
                save_checkpoint(cp)
                write_report(args, cp, df, schedule)
                print(err, file=sys.stderr)
                return 1

    if cp.get("stopped_reason") is None:
        cp["stopped_reason"] = "completed"
    save_checkpoint(cp)
    write_report(args, cp, df, schedule)
    print(
        json.dumps(
            {
                "ok": True,
                "stopped_reason": cp["stopped_reason"],
                "completed_pairs": sum(
                    1
                    for row in schedule
                    if row["date"] in cp["decisions"]["baseline"]
                    and row["date"] in cp["decisions"]["regime"]
                ),
                "estimated_cost_usd": round(completed_cost(cp), 4),
                "checkpoint": str(CHECKPOINT_PATH),
                "report": str(REPORT_PATH),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weeks", type=int, default=30)
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument("--reasoning-effort", default="none")
    parser.add_argument("--max-cost", type=float, default=3.20)
    parser.add_argument("--initial-run-cost-estimate", type=float, default=0.06)
    parser.add_argument("--input-price-per-m", type=float, default=DEFAULT_INPUT_PRICE_PER_M)
    parser.add_argument("--output-price-per-m", type=float, default=DEFAULT_OUTPUT_PRICE_PER_M)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--max-pairs", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_benchmark(parse_args()))
