"""Build a paper-aligned MeMo memory bank from high-variance trading states."""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent
TRADINGAGENTS_DIR = REPO_DIR / "TradingAgents"
DATA_DIR = BASE_DIR / "data" / "memo_adaptation"
sys.path.insert(0, str(REPO_DIR))
sys.path.insert(0, str(TRADINGAGENTS_DIR))

try:
    from dotenv import load_dotenv

    load_dotenv(TRADINGAGENTS_DIR / ".env", override=False)
except ImportError:
    pass

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.llm_clients import create_llm_client

    HAS_LLM = True
except ImportError:
    HumanMessage = None
    SystemMessage = None
    DEFAULT_CONFIG = {}
    create_llm_client = None
    HAS_LLM = False


GENERIC_PATTERNS = ["be careful", "monitor risks", "do more research", "remain cautious", "market is uncertain", "consider macro"]
OBSERVABLE_TERMS = ["rsi", "macd", "sma", "ema", "volume", "return", "drawdown", "price", "close", "trend", "reward", "sell", "buy", "hold", "underweight", "overweight"]
HORIZON_KEYS = ("1d", "5d", "20d")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def index_by(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    keys = ("trajectory_id", "reward_id", "input_id", "memory_id", "score_id")
    out = {}
    for row in rows:
        rid = next((row.get(k) for k in keys if row.get(k)), None)
        if rid:
            out[str(rid)] = row
    return out


def fnum(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_reward_weights(raw: str) -> dict[str, float]:
    weights: dict[str, float] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError(f"Invalid reward weight item: {item!r}")
        key, value = item.split("=", 1)
        key = key.strip().lower()
        if key not in HORIZON_KEYS:
            raise ValueError(f"Unsupported reward horizon in weights: {key!r}")
        weights[key] = float(value.strip())
    missing = [key for key in HORIZON_KEYS if key not in weights]
    if missing:
        raise ValueError(f"Missing reward weights for: {', '.join(missing)}")
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Reward weights must sum to a positive value")
    return {key: value / total for key, value in weights.items()}


def horizon_key(value: Any) -> str | None:
    text = str(value).strip().lower()
    if text.endswith("d"):
        return text if text in HORIZON_KEYS else None
    text = f"{text}d"
    return text if text in HORIZON_KEYS else None


def dense_match_ranks(participants: list[dict[str, Any]], tie_eps: float) -> dict[str, int]:
    ranked: dict[str, int] = {}
    previous_reward: float | None = None
    current_rank = 0
    for position, participant in enumerate(participants):
        reward = float(participant["match_reward"])
        if previous_reward is not None and abs(previous_reward - reward) > tie_eps:
            current_rank = position
        ranked[str(participant["trajectory_id"])] = current_rank + 1
        previous_reward = reward
    return ranked


def comparison_group_for(row: dict[str, Any]) -> str:
    return str(row.get("comparison_group") or ("baseline_no_memory" if row.get("memory_policy_id") == "mem_none_v1" else "memory_enabled"))


def memory_bank_version_for(row: dict[str, Any]) -> str:
    return str(row.get("memory_bank_version") or ("none" if row.get("memory_policy_id") == "mem_none_v1" else "unknown"))


def get_input_for_traj(traj: dict[str, Any], inputs: dict[str, dict[str, Any]], context_policy_id: str) -> dict[str, Any]:
    input_id = traj.get("input_id")
    if input_id in inputs:
        return inputs[input_id]
    if context_policy_id != "ctx_default_v1":
        return inputs.get(f"{traj.get('symbol')}_{traj.get('analysis_time')}_{context_policy_id}", {})
    return {}


def bucket_rsi(rsi: float | None) -> str:
    if rsi is None:
        return "rsi_unknown"
    if rsi < 30:
        return "rsi_oversold"
    if rsi < 45:
        return "rsi_weak"
    if rsi <= 55:
        return "rsi_neutral"
    if rsi <= 70:
        return "rsi_strong"
    return "rsi_overbought"


def bucket_return(ret: float | None) -> str:
    if ret is None:
        return "return_unknown"
    if ret <= -0.08:
        return "return_sharp_down"
    if ret < -0.02:
        return "return_down"
    if ret <= 0.02:
        return "return_flat"
    if ret < 0.08:
        return "return_up"
    return "return_sharp_up"


def context_features(input_data: dict[str, Any]) -> dict[str, Any]:
    latest = input_data.get("latest_market_snapshot") or {}
    window = input_data.get("market_window") or []
    if not latest and window:
        latest = window[-1]
    tech = input_data.get("technical_snapshot") or {}
    close = fnum(latest.get("close") or tech.get("close"))
    sma50 = fnum(tech.get("sma_50") or tech.get("close_50_sma"))
    sma200 = fnum(tech.get("sma_200") or tech.get("close_200_sma"))
    rsi = fnum(tech.get("rsi") or tech.get("rsi_14"))
    macd = fnum(tech.get("macd"))
    volume = fnum(latest.get("volume"))
    ret = None
    if len(window) >= 2:
        first = fnum(window[0].get("close"))
        last = fnum(window[-1].get("close"))
        if first not in (None, 0) and last is not None:
            ret = last / first - 1.0

    ma_state = "ma_unknown"
    if close is not None and sma50 is not None and sma200 is not None:
        if close < sma50 and close < sma200:
            ma_state = "below_sma50_sma200"
        elif close >= sma50 and close >= sma200:
            ma_state = "above_sma50_sma200"
        elif close >= sma50 and close < sma200:
            ma_state = "above_sma50_below_sma200"
        else:
            ma_state = "below_sma50_above_sma200"

    macd_state = "macd_unknown" if macd is None else ("macd_negative" if macd < 0 else "macd_positive")
    bearish = int(ma_state.startswith("below")) + int(macd is not None and macd < 0) + int(rsi is not None and rsi < 45) + int(ret is not None and ret < -0.02)
    bullish = int(ma_state.startswith("above")) + int(macd is not None and macd >= 0) + int(rsi is not None and rsi > 55) + int(ret is not None and ret > 0.02)
    regime = "bearish_momentum" if bearish >= 2 else ("bullish_momentum" if bullish >= 2 else "mixed_regime")

    triggers = []
    if close is not None and sma50 is not None:
        triggers.append(f"close {close:.2f} is {'below' if close < sma50 else 'above'} SMA50 {sma50:.2f}")
    if close is not None and sma200 is not None:
        triggers.append(f"close {close:.2f} is {'below' if close < sma200 else 'above'} SMA200 {sma200:.2f}")
    if rsi is not None:
        triggers.append(f"RSI {rsi:.2f} ({bucket_rsi(rsi)})")
    if macd is not None:
        triggers.append(f"MACD {macd:.4f} ({macd_state})")
    if ret is not None:
        triggers.append(f"15-row return {ret:.2%} ({bucket_return(ret)})")
    if volume is not None:
        triggers.append(f"volume {volume:.0f}")
    return {
        "market_regime": regime,
        "ma_state": ma_state,
        "rsi_bucket": bucket_rsi(rsi),
        "macd_state": macd_state,
        "return_bucket": bucket_return(ret),
        "trigger_conditions": triggers,
    }


def make_state_key(symbol: str, analysis_time: str, features: dict[str, Any], granularity: str) -> str:
    if granularity == "match":
        return f"{symbol}|{analysis_time}"
    parts = []
    if granularity == "symbol_regime":
        parts.append(symbol)
    parts.extend([features["market_regime"], features["ma_state"], features["rsi_bucket"], features["macd_state"]])
    if granularity != "coarse":
        parts.append(features["return_bucket"])
    return "|".join(parts)


def compact_report(traj: dict[str, Any], max_chars: int = 500) -> str:
    outputs = traj.get("agent_outputs") or {}
    report = outputs.get("market_report") or outputs.get("investment_plan") or outputs.get("full_report") or ""
    return str(report).replace("\n", " ")[:max_chars]


def build_states(args: argparse.Namespace, trajectories: dict[str, dict[str, Any]], rewards: list[dict[str, Any]], inputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if args.selection_mode == "reward_20d_legacy":
        return build_states_legacy_20d(args, trajectories, rewards, inputs)

    weights = parse_reward_weights(args.reward_weights)
    rewards_by_trajectory: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for reward in rewards:
        tid = str(reward.get("trajectory_id") or "")
        key = horizon_key(reward.get("horizon_days"))
        total_reward = fnum(reward.get("total_reward"))
        if tid in trajectories and key and total_reward is not None:
            rewards_by_trajectory[tid][key] = reward

    matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tid, traj in trajectories.items():
        horizon_rewards = rewards_by_trajectory.get(tid, {})
        if not all(key in horizon_rewards for key in HORIZON_KEYS):
            continue
        symbol = str(traj.get("symbol") or horizon_rewards["20d"].get("symbol") or "UNKNOWN")
        analysis_time = str(traj.get("analysis_time") or traj.get("episode_id") or "unknown_time")
        per_horizon = {
            key: float(horizon_rewards[key]["total_reward"])
            for key in HORIZON_KEYS
        }
        match_reward = sum(weights[key] * per_horizon[key] for key in HORIZON_KEYS)
        matches[f"{symbol}|{analysis_time}"].append(
            {
                "trajectory_id": tid,
                "traj": traj,
                "symbol": symbol,
                "analysis_time": analysis_time,
                "prompt_set_id": traj.get("prompt_set_id"),
                "final_action": horizon_rewards["20d"].get("final_action"),
                "match_reward": match_reward,
                "per_horizon": per_horizon,
                "reward_ids_by_horizon": {
                    key: horizon_rewards[key].get("reward_id")
                    for key in HORIZON_KEYS
                },
                "alpha_return_20d": horizon_rewards["20d"].get("alpha_return"),
                "max_drawdown_horizon_20d": horizon_rewards["20d"].get("max_drawdown_horizon"),
            }
        )

    states: dict[str, dict[str, Any]] = {}
    for match_id, participants in matches.items():
        if len(participants) < args.min_match_candidates:
            continue

        rewards_in_match = [p["match_reward"] for p in participants]
        dispersion = max(rewards_in_match) - min(rewards_in_match)
        if dispersion < args.min_match_dispersion:
            continue

        participants_sorted = sorted(participants, key=lambda p: p["match_reward"], reverse=True)
        rank_by_tid = dense_match_ranks(participants_sorted, args.tie_eps)
        max_rank = max(rank_by_tid.values())
        exemplar = participants_sorted[0]["traj"]
        features = context_features(get_input_for_traj(exemplar, inputs, args.context_policy_id))
        symbol = participants_sorted[0]["symbol"]
        analysis_time = participants_sorted[0]["analysis_time"]
        state_key = make_state_key(symbol, analysis_time, features, args.state_granularity)
        state = states.setdefault(
            state_key,
            {
                "state_key": state_key,
                "symbol": symbol if args.state_granularity in ("symbol_regime", "match") else "ANY",
                "market_regime": features["market_regime"],
                "state_features": {k: features[k] for k in ["market_regime", "ma_state", "rsi_bucket", "macd_state", "return_bucket"]},
                "trigger_conditions": features["trigger_conditions"],
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "rewards": [],
                "match_dispersions": [],
                "matched_state_ids": [],
                "examples": [],
                "actions": Counter(),
                "prompts": Counter(),
                "selection_mode": args.selection_mode,
                "reward_weights": weights,
            },
        )
        state["matched_state_ids"].append(match_id)
        state["match_dispersions"].append(dispersion)

        for p in participants_sorted:
            match_reward = p["match_reward"]
            match_rank = rank_by_tid[p["trajectory_id"]]
            if match_rank == 1:
                state["wins"] += 1
            elif match_rank == max_rank:
                state["losses"] += 1
            else:
                state["draws"] += 1
            state["rewards"].append(match_reward)
            state["actions"][str(p.get("final_action") or "Unknown")] += 1
            state["prompts"][str(p.get("prompt_set_id") or "unknown")] += 1
            state["examples"].append(
                {
                    "reward_id": p["reward_ids_by_horizon"].get("20d"),
                    "reward_ids_by_horizon": p["reward_ids_by_horizon"],
                    "trajectory_id": p["trajectory_id"],
                    "analysis_time": p["analysis_time"],
                    "symbol": p["symbol"],
                    "prompt_set_id": p["prompt_set_id"],
                    "final_action": p["final_action"],
                    "total_reward": match_reward,
                    "match_reward": match_reward,
                    "match_rank": match_rank,
                    "match_candidate_count": len(participants),
                    "match_dispersion": dispersion,
                    "reward_1d": p["per_horizon"]["1d"],
                    "reward_5d": p["per_horizon"]["5d"],
                    "reward_20d": p["per_horizon"]["20d"],
                    "alpha_return": p["alpha_return_20d"],
                    "max_drawdown_horizon": p["max_drawdown_horizon_20d"],
                    "report_excerpt": compact_report(p["traj"]),
                }
            )
    return states


def build_states_legacy_20d(args: argparse.Namespace, trajectories: dict[str, dict[str, Any]], rewards: list[dict[str, Any]], inputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for reward in rewards:
        if reward.get("horizon_days") != 20:
            continue
        total_reward = fnum(reward.get("total_reward"))
        if total_reward is None:
            continue
        traj = trajectories.get(str(reward.get("trajectory_id")))
        if not traj:
            continue
        features = context_features(get_input_for_traj(traj, inputs, args.context_policy_id))
        symbol = str(reward.get("symbol") or traj.get("symbol"))
        state_key = make_state_key(symbol, str(traj.get("analysis_time") or ""), features, args.state_granularity)
        state = states.setdefault(
            state_key,
            {
                "state_key": state_key,
                "symbol": symbol if args.state_granularity == "symbol_regime" else "ANY",
                "market_regime": features["market_regime"],
                "state_features": {k: features[k] for k in ["market_regime", "ma_state", "rsi_bucket", "macd_state", "return_bucket"]},
                "trigger_conditions": features["trigger_conditions"],
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "rewards": [],
                "examples": [],
                "actions": Counter(),
                "prompts": Counter(),
                "selection_mode": args.selection_mode,
            },
        )
        if total_reward > args.outcome_eps:
            state["wins"] += 1
        elif total_reward < -args.outcome_eps:
            state["losses"] += 1
        else:
            state["draws"] += 1
        state["rewards"].append(total_reward)
        state["actions"][str(reward.get("final_action") or "Unknown")] += 1
        state["prompts"][str(reward.get("prompt_set_id") or "unknown")] += 1
        state["examples"].append(
            {
                "reward_id": reward.get("reward_id"),
                "trajectory_id": reward.get("trajectory_id"),
                "analysis_time": traj.get("analysis_time"),
                "symbol": symbol,
                "prompt_set_id": reward.get("prompt_set_id"),
                "final_action": reward.get("final_action"),
                "total_reward": total_reward,
                "alpha_return": reward.get("alpha_return"),
                "max_drawdown_horizon": reward.get("max_drawdown_horizon"),
                "report_excerpt": compact_report(traj),
            }
        )
    return states


def select_high_variance_states(states: dict[str, dict[str, Any]], min_count: int, top_k: int) -> list[dict[str, Any]]:
    selected = []
    for state in states.values():
        count = len(state["rewards"])
        if count < min_count or state["wins"] == 0 or state["losses"] == 0:
            continue
        state["count"] = count
        state["mean_match_reward"] = float(mean(state["rewards"]))
        state["std_match_reward"] = float(pstdev(state["rewards"])) if count > 1 else 0.0
        state["mean_reward_20d"] = state["mean_match_reward"]
        state["std_reward_20d"] = state["std_match_reward"]
        state["max_match_dispersion"] = float(max(state.get("match_dispersions") or [state["std_match_reward"]]))
        state["mean_match_dispersion"] = float(mean(state.get("match_dispersions") or [state["std_match_reward"]]))
        state["matched_state_count"] = len(state.get("matched_state_ids") or [])
        state["interestingness"] = float(
            state["max_match_dispersion"] * math.log1p(state["matched_state_count"] or count)
            + state["std_match_reward"] * math.log1p(count)
            + 0.01
            + 0.002 * len(state["actions"])
        )
        state["actions"] = dict(state["actions"])
        state["prompts"] = dict(state["prompts"])
        if state.get("selection_mode") == "trueskill_match":
            state["winning_examples"] = sorted(
                [e for e in state["examples"] if e.get("match_rank") == 1],
                key=lambda x: x["total_reward"],
                reverse=True,
            )[:4]
            max_rank = max((int(e.get("match_rank") or 0) for e in state["examples"]), default=0)
            state["losing_examples"] = sorted(
                [e for e in state["examples"] if e.get("match_rank") == max_rank],
                key=lambda x: x["total_reward"],
            )[:4]
        else:
            state["winning_examples"] = sorted([e for e in state["examples"] if e["total_reward"] > 0], key=lambda x: x["total_reward"], reverse=True)[:4]
            state["losing_examples"] = sorted([e for e in state["examples"] if e["total_reward"] < 0], key=lambda x: x["total_reward"])[:4]
        selected.append(state)
    selected.sort(key=lambda x: x["interestingness"], reverse=True)
    return selected[:top_k]


def create_llm(model: str | None):
    if not HAS_LLM:
        raise RuntimeError("LLM dependencies unavailable")
    config = DEFAULT_CONFIG.copy()
    return create_llm_client(
        provider=config["llm_provider"],
        model=model or config["quick_think_llm"],
        base_url=config.get("backend_url"),
        temperature=0.0,
    ).get_llm()


def parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def state_prompt(state: dict[str, Any]) -> str:
    payload = {
        "strategic_state_view": {
            "state_key": state["state_key"],
            "symbol_scope": state["symbol"],
            "state_features": state["state_features"],
            "trigger_conditions": state["trigger_conditions"],
            "action_distribution": state["actions"],
            "prompt_distribution": state["prompts"],
        },
        "strategic_state_outcomes": {
            "wins": state["wins"],
            "losses": state["losses"],
            "draws": state["draws"],
            "count": state["count"],
            "selection_mode": state.get("selection_mode"),
            "reward_weights": state.get("reward_weights"),
            "mean_match_reward": state.get("mean_match_reward"),
            "std_match_reward": state.get("std_match_reward"),
            "max_match_dispersion": state.get("max_match_dispersion"),
            "mean_match_dispersion": state.get("mean_match_dispersion"),
            "matched_state_count": state.get("matched_state_count"),
            "interestingness": state["interestingness"],
        },
        "winning_examples": state["winning_examples"],
        "losing_examples": state["losing_examples"],
    }
    return (
        "You are the MeMo Trajectory Reflection module adapted to trading.\n"
        "This state was selected because prompt sets diverged on the same point-in-time market state.\n"
        "The tournament outcome uses match_reward = weighted 1d/5d/20d reward, matching the TrueSkill scorer.\n"
        "Explain why this state is strategically decisive and produce one actionable memory.\n\n"
        f"STATE DATA:\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n\n"
        "Return JSON only with fields: candidate_id, lesson_type, strategic_state_summary, why_decisive, "
        "actionable_adjustment, trigger_conditions, do, avoid, apply_when, do_not_apply_when, evidence_summary.\n"
        "Hard requirements: explain why same-input prompt winners and losers diverged; give concrete do/avoid; include at least 3 observable triggers; say when not to apply the lesson."
    )


def rule_based_reflection(state: dict[str, Any], idx: int) -> dict[str, Any]:
    actions = Counter(str(e.get("final_action") or "Unknown") for e in state["winning_examples"])
    best_action = actions.most_common(1)[0][0] if actions else "Hold"
    triggers = list(state.get("trigger_conditions") or [])[:6]
    while len(triggers) < 3:
        triggers.append(f"state {state['state_key']} had mixed 20d outcomes")
    return {
        "candidate_id": f"cand_{idx:03d}",
        "lesson_type": "high_variance_state",
        "strategic_state_summary": f"{state['state_key']} produced {state['wins']} relative wins, {state['losses']} relative losses, {state['draws']} middle/tied outcomes.",
        "why_decisive": f"This state is decisive because match-reward dispersion reached {state.get('max_match_dispersion', state.get('std_reward_20d', 0.0)):.6f}; winners usually aligned exposure with {best_action}, while losers did not respect the trigger set.",
        "actionable_adjustment": f"When at least three triggers match, treat {best_action} as a prior only if current evidence confirms the same regime; otherwise reduce to Hold/Underweight.",
        "trigger_conditions": triggers,
        "do": f"Prefer {best_action} only when at least three stored triggers match and the current report confirms the same regime.",
        "avoid": "Do not apply this lesson when symbol, regime, moving-average alignment, MACD, RSI, or recent return bucket differs materially.",
        "apply_when": triggers[:4],
        "do_not_apply_when": ["fewer than three triggers match", "news or macro evidence contradicts the stored regime"],
        "evidence_summary": {},
    }


def llm_reflection(llm, state: dict[str, Any], idx: int) -> dict[str, Any]:
    response = llm.invoke(
        [
            SystemMessage(content="You write precise MeMo trading memories from high-variance historical states. Return JSON only."),
            HumanMessage(content=state_prompt(state)),
        ]
    )
    parsed = parse_json_object(str(getattr(response, "content", response)))
    if not parsed:
        raise RuntimeError("reflection returned non-JSON")
    parsed.setdefault("candidate_id", f"cand_{idx:03d}")
    return parsed


def quality_gate(candidate: dict[str, Any]) -> tuple[bool, list[str], float]:
    flags = []
    text = " ".join(str(candidate.get(k, "")) for k in ["why_decisive", "actionable_adjustment", "do", "avoid"]).lower()
    triggers = candidate.get("trigger_conditions") if isinstance(candidate.get("trigger_conditions"), list) else []
    trigger_text = " ".join(str(t).lower() for t in triggers)
    if len(triggers) < 3:
        flags.append("too_few_triggers")
    if any(p in text for p in GENERIC_PATTERNS):
        flags.append("generic_text")
    if not any(term in trigger_text or term in text for term in OBSERVABLE_TERMS):
        flags.append("missing_observable_terms")
    if len(str(candidate.get("do", ""))) < 40:
        flags.append("weak_do")
    if len(str(candidate.get("avoid", ""))) < 40:
        flags.append("weak_avoid")
    score = 0.55 + min(len(triggers), 6) * 0.05
    score += 0.12 if "generic_text" not in flags else 0
    score += 0.12 if "missing_observable_terms" not in flags else 0
    score += 0.06 if "weak_do" not in flags else 0
    score += 0.06 if "weak_avoid" not in flags else 0
    return not flags, flags, min(0.99, max(0.0, score))


def candidate_text(candidate: dict[str, Any]) -> str:
    return (
        f"ID={candidate.get('candidate_id')} | SUMMARY={candidate.get('strategic_state_summary', '')} | "
        f"WHY={candidate.get('why_decisive', '')} | ADJUST={candidate.get('actionable_adjustment', '')} | "
        f"DO={candidate.get('do', '')} | AVOID={candidate.get('avoid', '')} | TRIGGERS={candidate.get('trigger_conditions', [])}"
    )


def crud_prompt(candidates: list[dict[str, Any]], existing: list[dict[str, Any]]) -> str:
    new_text = "\n".join(f"{i + 1}. {candidate_text(c)}" for i, c in enumerate(candidates))
    old_text = "\n".join(f"{i + 1}. {m.get('lesson', '')}" for i, m in enumerate(existing)) if existing else "[EMPTY MEMORY LIBRARY]"
    empty_note = "The existing library is empty, so use ADD operations only." if not existing else ""
    return f"""You are the MeMo Memory Operation module for a trading memory bank.
Maintain a compact, actionable library by adding, editing, or removing lessons.

NEW HIGH-VARIANCE STATE REFLECTIONS:
{new_text}

EXISTING MEMORY LIBRARY:
{old_text}

{empty_note}

Use simple tags only:
<add candidate_id="cand_001">new or refined actionable memory</add>
<edit number="3" candidate_id="cand_004">replacement memory text</edit>
<remove number="5">reason</remove>

Quality requirements:
- ADD only lessons with concrete observable triggers and clear do/avoid behavior.
- EDIT to merge overlapping lessons into one stronger rule.
- REMOVE lessons that are contradictory, redundant, stale, or lack actionable guidance.
- Each memory should explain why the state matters and when not to apply it.
- Do not add generic advice such as merely "monitor risk" or "be cautious".

Generate operations below:
"""


def parse_ops(text: str) -> list[dict[str, Any]]:
    ops = []
    tag_re = re.compile(r"<(add|edit|remove)([^>]*)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
    for match in tag_re.finditer(text):
        attrs = match.group(2) or ""
        number = re.search(r'number=["\']?(\d+)["\']?', attrs)
        cand = re.search(r'candidate_id=["\']?([A-Za-z0-9_.:-]+)["\']?', attrs)
        ops.append(
            {
                "op": match.group(1).lower(),
                "number": int(number.group(1)) if number else None,
                "candidate_id": cand.group(1) if cand else None,
                "content": match.group(3).strip(),
            }
        )
    return ops


def simple_add_ops(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "op": "add",
            "candidate_id": c.get("candidate_id"),
            "content": f"{c.get('why_decisive', '')} Adjustment: {c.get('actionable_adjustment', '')} Do: {c.get('do', '')} Avoid: {c.get('avoid', '')}",
        }
        for c in candidates
    ]


def llm_crud_ops(llm, candidates: list[dict[str, Any]], existing: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str]:
    prompt = crud_prompt(candidates, existing)
    response = llm.invoke(
        [
            SystemMessage(content="You perform MeMo memory CRUD. Use only the requested XML-like tags."),
            HumanMessage(content=prompt),
        ]
    )
    text = str(getattr(response, "content", response))
    ops = parse_ops(text)
    if not ops:
        raise RuntimeError("CRUD response had no parseable operations")
    return ops, prompt, text


def build_memory_record(args: argparse.Namespace, op: dict[str, Any], candidate: dict[str, Any] | None, index: int, method: str, q: float, flags: list[str]) -> dict[str, Any]:
    evidence = (candidate or {}).get("evidence_summary", {})
    state_key = evidence.get("state_key", "unknown_state")
    source_reward_ids = evidence.get("example_reward_ids", [])
    source_trajectory_ids = evidence.get("example_trajectory_ids", [])
    return {
        "memory_id": f"mem_{args.memory_bank_version}_{index:04d}",
        "memory_bank_version": args.memory_bank_version,
        "source_tournament_id": args.tournament_id,
        "source_score_scope_id": args.score_scope_id,
        "source_generation_id": "gen_2022_00",
        "source_prompt_set_id": "mixed_prompt_state",
        "source_trajectory_id": source_trajectory_ids[0] if source_trajectory_ids else None,
        "source_reward_id": source_reward_ids[0] if source_reward_ids else None,
        "source_reward_ids": source_reward_ids,
        "source_trajectory_ids": source_trajectory_ids,
        "source_time": None,
        "symbol": evidence.get("symbol", "ANY"),
        "agent_role": "trader",
        "lesson_type": (candidate or {}).get("lesson_type", "high_variance_state"),
        "market_regime": evidence.get("market_regime", "mixed_regime"),
        "state_key": state_key,
        "situation_summary": (candidate or {}).get("strategic_state_summary", f"High-variance state {state_key}"),
        "lesson": op.get("content", ""),
        "strategic_analysis": (candidate or {}).get("why_decisive") or op.get("content", ""),
        "actionable_adjustment": (candidate or {}).get("actionable_adjustment") or op.get("content", ""),
        "trigger_conditions": (candidate or {}).get("trigger_conditions", []),
        "do": (candidate or {}).get("do"),
        "avoid": (candidate or {}).get("avoid"),
        "use_when": (candidate or {}).get("apply_when") or (candidate or {}).get("trigger_conditions", []),
        "avoid_when": (candidate or {}).get("do_not_apply_when") or ([candidate.get("avoid")] if candidate and candidate.get("avoid") else []),
        "evidence_summary": evidence,
        "quality_score": q,
        "quality_flags": flags,
        "selection_mode": evidence.get("selection_mode"),
        "reward_weights": evidence.get("reward_weights"),
        "mean_match_reward": evidence.get("mean_match_reward"),
        "std_match_reward": evidence.get("std_match_reward"),
        "max_match_dispersion": evidence.get("max_match_dispersion"),
        "mean_match_dispersion": evidence.get("mean_match_dispersion"),
        "matched_state_count": evidence.get("matched_state_count"),
        "reward_20d": evidence.get("mean_reward_20d"),
        "max_drawdown_horizon": None,
        "final_action": None,
        "extraction_method": method,
        "memory_version": args.memory_bank_version,
        "created_at": pd.Timestamp.utcnow().isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build paper-aligned MeMo memory from high-variance trading states.")
    parser.add_argument("--tournament-id", required=True)
    parser.add_argument("--score-scope-id", default=None)
    parser.add_argument("--memory-bank-version", required=True)
    parser.add_argument("--data-mode", default="offline_materialized")
    parser.add_argument("--comparison-group", default="baseline_no_memory")
    parser.add_argument("--source-memory-bank-version", default="none")
    parser.add_argument("--context-policy-id", default="ctx_paper_aligned_v1")
    parser.add_argument("--train-start-date", default=None)
    parser.add_argument("--train-end-date", default=None)
    parser.add_argument("--state-granularity", choices=["match", "symbol_regime", "regime", "coarse"], default="match")
    parser.add_argument("--selection-mode", choices=["trueskill_match", "reward_20d_legacy"], default="trueskill_match")
    parser.add_argument("--reward-weights", default="1d=0.2,5d=0.3,20d=0.5")
    parser.add_argument("--min-match-candidates", type=int, default=2)
    parser.add_argument("--min-match-dispersion", type=float, default=0.0)
    parser.add_argument("--tie-eps", type=float, default=1e-12)
    parser.add_argument("--outcome-eps", type=float, default=0.001)
    parser.add_argument("--min-state-count", type=int, default=3)
    parser.add_argument("--top-states", type=int, default=30)
    parser.add_argument("--reflection-mode", choices=["llm", "rule_based"], default="llm")
    parser.add_argument("--crud-mode", choices=["llm", "simple_add"], default="llm")
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--replace-version", action="store_true")
    args = parser.parse_args()

    trajectories_all = index_by(load_jsonl(DATA_DIR / "trajectories" / "workflow_trajectories.jsonl"))
    rewards_all = load_jsonl(DATA_DIR / "rewards" / "trajectory_rewards.jsonl")
    inputs = index_by(load_jsonl(DATA_DIR / "materialized_inputs" / f"inputs_{args.context_policy_id}.jsonl"))
    memory_path = DATA_DIR / "memory_bank" / "memo_memory_bank.jsonl"
    memories_all = load_jsonl(memory_path)

    trajectories = {}
    for tid, traj in trajectories_all.items():
        if traj.get("tournament_id") != args.tournament_id or traj.get("run_status") != "succeeded":
            continue
        if args.data_mode and traj.get("data_mode") != args.data_mode:
            continue
        if args.comparison_group and comparison_group_for(traj) != args.comparison_group:
            continue
        if args.source_memory_bank_version and memory_bank_version_for(traj) != args.source_memory_bank_version:
            continue
        day = str(traj.get("analysis_time", ""))[:10]
        if args.train_start_date and day < args.train_start_date:
            continue
        if args.train_end_date and day > args.train_end_date:
            continue
        trajectories[tid] = traj

    rewards = [r for r in rewards_all if r.get("tournament_id") == args.tournament_id and str(r.get("trajectory_id")) in trajectories]
    logger.info("Selected %d trajectories and %d rewards for high-variance selection.", len(trajectories), len(rewards))
    states = build_states(args, trajectories, rewards, inputs)
    selected_states = select_high_variance_states(states, args.min_state_count, args.top_states)
    logger.info("Selected %d high-variance states from %d state buckets.", len(selected_states), len(states))
    if not selected_states:
        raise SystemExit("No high-variance states selected. Lower --min-state-count or use --state-granularity regime/coarse.")

    llm = create_llm(args.llm_model) if args.reflection_mode == "llm" or args.crud_mode == "llm" else None
    candidates = []
    reflection_errors = 0
    for idx, state in enumerate(selected_states, start=1):
        try:
            cand = llm_reflection(llm, state, idx) if args.reflection_mode == "llm" else rule_based_reflection(state, idx)
        except Exception as exc:
            reflection_errors += 1
            logger.warning("Reflection failed for %s: %s; using rule-based fallback.", state["state_key"], exc)
            cand = rule_based_reflection(state, idx)
        cand["candidate_id"] = cand.get("candidate_id") or f"cand_{idx:03d}"
        if not isinstance(cand.get("evidence_summary"), dict):
            cand["evidence_summary"] = {}
        cand.setdefault("evidence_summary", {})
        cand["evidence_summary"].update(
            {
                "state_key": state["state_key"],
                "symbol": state["symbol"],
                "market_regime": state["market_regime"],
                "wins": state["wins"],
                "losses": state["losses"],
                "draws": state["draws"],
                "count": state["count"],
                "selection_mode": state.get("selection_mode"),
                "reward_weights": state.get("reward_weights"),
                "matched_state_ids": state.get("matched_state_ids", []),
                "matched_state_count": state.get("matched_state_count"),
                "mean_match_reward": state.get("mean_match_reward"),
                "std_match_reward": state.get("std_match_reward"),
                "max_match_dispersion": state.get("max_match_dispersion"),
                "mean_match_dispersion": state.get("mean_match_dispersion"),
                "mean_reward_20d": state["mean_reward_20d"],
                "std_reward_20d": state["std_reward_20d"],
                "interestingness": state["interestingness"],
                "example_reward_ids": [e["reward_id"] for e in (state["winning_examples"] + state["losing_examples"])],
                "example_reward_ids_by_horizon": [e.get("reward_ids_by_horizon", {}) for e in (state["winning_examples"] + state["losing_examples"])],
                "example_trajectory_ids": [e["trajectory_id"] for e in (state["winning_examples"] + state["losing_examples"])],
            }
        )
        passed, flags, q = quality_gate(cand)
        cand["quality_flags"] = flags
        cand["quality_score"] = q
        if passed:
            candidates.append(cand)
    logger.info("Generated %d quality-passing candidates; reflection_errors=%d.", len(candidates), reflection_errors)
    if not candidates:
        raise SystemExit("No reflection candidates passed quality gate.")

    existing_target = [m for m in memories_all if m.get("memory_bank_version") == args.memory_bank_version]
    if args.replace_version:
        memories_all = [m for m in memories_all if m.get("memory_bank_version") != args.memory_bank_version]
        existing_target = []
        logger.info("Removed existing memories for version %s before rebuild.", args.memory_bank_version)

    try:
        if args.crud_mode == "llm":
            ops, crud_prompt_text, crud_response_text = llm_crud_ops(llm, candidates, existing_target)
            method = "memo_high_variance_trueskill_match_llm_reflection_crud_v1" if args.selection_mode == "trueskill_match" else "memo_high_variance_llm_reflection_crud_v1"
        else:
            ops = simple_add_ops(candidates)
            crud_prompt_text = ""
            crud_response_text = ""
            method = "memo_high_variance_trueskill_match_rule_based_simple_add_v1" if args.selection_mode == "trueskill_match" else "memo_high_variance_rule_based_simple_add_v1"
    except Exception as exc:
        logger.warning("LLM CRUD failed: %s; falling back to simple_add.", exc)
        ops = simple_add_ops(candidates)
        crud_prompt_text = ""
        crud_response_text = ""
        method = "memo_high_variance_trueskill_match_simple_add_fallback_v1" if args.selection_mode == "trueskill_match" else "memo_high_variance_simple_add_fallback_v1"

    cand_by_id = {str(c["candidate_id"]): c for c in candidates}
    new_target = []
    add_index = 0
    for op in ops:
        if op["op"] != "add":
            continue
        cand = cand_by_id.get(str(op.get("candidate_id")))
        if cand is None and add_index < len(candidates):
            cand = candidates[add_index]
            op["candidate_id"] = cand.get("candidate_id")
        add_index += 1
        passed, flags, q = quality_gate(cand) if cand else (True, [], 0.7)
        if not passed:
            continue
        new_target.append(build_memory_record(args, op, cand, len(new_target) + 1, method, q, flags))

    final_memories = [m for m in memories_all if m.get("memory_bank_version") != args.memory_bank_version] + new_target
    write_jsonl(memory_path, final_memories)

    debug_dir = DATA_DIR / "memory_bank" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    with open(debug_dir / f"{args.memory_bank_version}_debug.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "args": vars(args),
                "selected_states": selected_states,
                "candidates": candidates,
                "ops": ops,
                "crud_prompt": crud_prompt_text,
                "crud_response": crud_response_text,
                "reflection_errors": reflection_errors,
                "created_at": pd.Timestamp.utcnow().isoformat(),
            },
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    manifest = {
        "dataset_version": args.memory_bank_version,
        "count_total_memories": len(final_memories),
        "count_version_memories": len(new_target),
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "source_tournament_id": args.tournament_id,
        "source_score_scope_id": args.score_scope_id,
        "train_start_date": args.train_start_date,
        "train_end_date": args.train_end_date,
        "selection_mode": args.selection_mode,
        "reward_weights": parse_reward_weights(args.reward_weights) if args.selection_mode == "trueskill_match" else None,
        "min_match_candidates": args.min_match_candidates,
        "min_match_dispersion": args.min_match_dispersion,
        "tie_eps": args.tie_eps,
        "state_granularity": args.state_granularity,
        "selected_state_count": len(selected_states),
        "candidate_count": len(candidates),
        "operation_count": len(ops),
        "reflection_mode": args.reflection_mode,
        "crud_mode": args.crud_mode,
        "extraction_method": method,
        "reflection_errors": reflection_errors,
    }
    with open(DATA_DIR / "memory_bank" / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    logger.info("Wrote %d memories for version %s", len(new_target), args.memory_bank_version)
    logger.info("Debug artifact: %s", debug_dir / f"{args.memory_bank_version}_debug.json")


if __name__ == "__main__":
    main()
