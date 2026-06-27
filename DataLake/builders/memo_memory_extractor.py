import argparse
import json
import logging
import re
import sys
from pathlib import Path
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

GENERIC_PHRASES = [
    "be careful",
    "monitor risks",
    "consider macro",
    "remain cautious",
    "exercise caution",
    "do more research",
    "market conditions are uncertain",
    "preserve the evidence pattern",
    "re-evaluate momentum vs macro",
    "in similar point-in-time contexts",
]
INDICATOR_TERMS = [
    "rsi",
    "macd",
    "sma",
    "ema",
    "moving average",
    "volume",
    "drawdown",
    "alpha",
    "20d",
    "50dma",
    "200dma",
    "below",
    "above",
    "reward",
    "sell",
    "underweight",
    "overweight",
    "hold",
    "buy",
]


def load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            record_id = (
                record.get("memory_id")
                or record.get("score_id")
                or record.get("reward_id")
                or record.get("trajectory_id")
                or record.get("input_id")
            )
            if record_id:
                records[record_id] = record
    return records


def upsert_jsonl(path: Path, key: str, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    replaced = False
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                existing = json.loads(line)
                if existing.get(key) == record.get(key):
                    if not replaced:
                        rows.append(record)
                        replaced = True
                else:
                    rows.append(existing)
    if not replaced:
        rows.append(record)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")


def rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")


def comparison_group_for(row: dict[str, Any]) -> str:
    explicit = row.get("comparison_group")
    if explicit:
        return str(explicit)
    return "baseline_no_memory" if row.get("memory_policy_id") == "mem_none_v1" else "memory_enabled"


def memory_bank_version_for(row: dict[str, Any]) -> str:
    return str(row.get("memory_bank_version") or "none")


def selected_rewards_by_extremes(rewards: list[dict[str, Any]], max_memories: int) -> list[dict[str, Any]]:
    rewards_20d = [
        r for r in rewards if r.get("horizon_days") == 20 and r.get("total_reward") is not None
    ]
    if not rewards_20d:
        return []

    bucket_size = max(1, max_memories // 3)
    top_winners = sorted(rewards_20d, key=lambda x: x["total_reward"], reverse=True)[:bucket_size]
    bottom_losers = sorted(rewards_20d, key=lambda x: x["total_reward"])[:bucket_size]
    worst_drawdown = sorted(
        rewards_20d,
        key=lambda x: x.get("max_drawdown_horizon") if x.get("max_drawdown_horizon") is not None else 0.0,
    )[:bucket_size]

    selected: dict[str, dict[str, Any]] = {}
    for reward in top_winners + bottom_losers + worst_drawdown:
        selected[reward["reward_id"]] = reward
    return list(selected.values())[:max_memories]


def fnum(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def get_technical_snapshot(input_data: dict[str, Any]) -> dict[str, Any]:
    return input_data.get("technical_snapshot") or {}


def get_latest_market(input_data: dict[str, Any]) -> dict[str, Any]:
    return input_data.get("latest_market_snapshot") or {}


def compact_news(items: list[dict[str, Any]], max_items: int = 5) -> list[str]:
    out = []
    for item in items[:max_items]:
        title = item.get("title") or item.get("summary") or item.get("text") or ""
        event_time = item.get("event_time") or item.get("known_time") or item.get("date") or ""
        if title:
            out.append(f"{event_time}: {title}"[:240])
    return out


def build_context_features(input_data: dict[str, Any]) -> dict[str, Any]:
    latest = get_latest_market(input_data)
    tech = get_technical_snapshot(input_data)
    market_window = input_data.get("market_window") or []
    first = market_window[0] if market_window else {}
    last = market_window[-1] if market_window else latest

    close = fnum(last.get("close") or latest.get("close") or tech.get("close"))
    first_close = fnum(first.get("close"))
    volume = fnum(last.get("volume") or latest.get("volume"))
    rsi = fnum(tech.get("rsi") or tech.get("rsi_14"))
    macd = fnum(tech.get("macd"))
    sma20 = fnum(tech.get("sma_20") or tech.get("close_20_sma"))
    sma50 = fnum(tech.get("sma_50") or tech.get("close_50_sma"))
    sma200 = fnum(tech.get("sma_200") or tech.get("close_200_sma"))

    window_return = None
    if close is not None and first_close not in (None, 0):
        window_return = (close / first_close) - 1.0

    triggers = []
    if close is not None and sma50 is not None:
        relation = "below" if close < sma50 else "above"
        triggers.append(f"close {close:.2f} is {relation} SMA50 {sma50:.2f}")
    if close is not None and sma200 is not None:
        relation = "below" if close < sma200 else "above"
        triggers.append(f"close {close:.2f} is {relation} SMA200 {sma200:.2f}")
    if rsi is not None:
        triggers.append(f"RSI is {rsi:.2f}")
    if macd is not None:
        sign = "negative" if macd < 0 else "positive"
        triggers.append(f"MACD is {sign} at {macd:.4f}")
    if window_return is not None:
        triggers.append(f"recent {len(market_window)}-row price return is {window_return:.2%}")
    if volume is not None:
        triggers.append(f"latest volume is {volume:.0f}")

    news = compact_news(input_data.get("ticker_news_window") or [], 5)
    macro_news = compact_news(input_data.get("macro_news_window") or [], 3)
    if news:
        triggers.append(f"ticker news count in window is {len(input_data.get('ticker_news_window') or [])}")
    if macro_news:
        triggers.append(f"macro news count in window is {len(input_data.get('macro_news_window') or [])}")

    return {
        "close": close,
        "rsi": rsi,
        "macd": macd,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "window_return": window_return,
        "trigger_conditions": triggers,
        "news_headlines": news,
        "macro_headlines": macro_news,
    }


def infer_regime(features: dict[str, Any]) -> str:
    bearish = 0
    bullish = 0
    close = features.get("close")
    for ma in (features.get("sma50"), features.get("sma200")):
        if close is not None and ma is not None:
            bearish += int(close < ma)
            bullish += int(close >= ma)
    macd = features.get("macd")
    if macd is not None:
        bearish += int(macd < 0)
        bullish += int(macd >= 0)
    rsi = features.get("rsi")
    if rsi is not None:
        bearish += int(rsi < 45)
        bullish += int(rsi > 55)
    if bearish >= 2:
        return "bearish_momentum"
    if bullish >= 2:
        return "bullish_momentum"
    return "mixed_regime"


def summarize_agent_output(traj: dict[str, Any], max_chars: int = 1600) -> str:
    outputs = traj.get("agent_outputs") or {}
    text = outputs.get("market_report") or outputs.get("investment_plan") or ""
    return text[:max_chars]


def build_reflection_payload(
    reward: dict[str, Any],
    traj: dict[str, Any],
    input_data: dict[str, Any],
    score_by_prompt: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    features = build_context_features(input_data)
    score = score_by_prompt.get(reward.get("prompt_set_id"), {})
    return {
        "symbol": reward.get("symbol"),
        "analysis_time": traj.get("analysis_time"),
        "prompt_set_id": reward.get("prompt_set_id"),
        "prompt_rank_full_year": score.get("rank"),
        "final_action": reward.get("final_action"),
        "reward_20d": reward.get("total_reward"),
        "alpha_return": reward.get("alpha_return"),
        "future_return": reward.get("future_return"),
        "max_drawdown_horizon": reward.get("max_drawdown_horizon"),
        "context_features": features,
        "agent_report_excerpt": summarize_agent_output(traj),
    }


def rule_based_reflection(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("final_action") or "Unknown"
    reward = float(payload.get("reward_20d") or 0.0)
    drawdown = float(payload.get("max_drawdown_horizon") or 0.0)
    features = payload.get("context_features") or {}
    triggers = list(features.get("trigger_conditions") or [])[:6]
    while len(triggers) < 2:
        triggers.append(f"20d reward outcome was {reward:.6f} for action {action}")

    if reward > 0:
        lesson_type = "positive"
        strategic = (
            f"The {action} exposure worked because the observed setup aligned with the subsequent 20d alpha reward "
            f"of {reward:.6f}. The important state variables were: {'; '.join(triggers[:3])}."
        )
        do = f"When at least two of these triggers reappear, allow a similar {action} bias but keep the decision tied to the listed indicators."
        avoid = "Do not generalize this lesson if price/RSI/MACD conditions no longer match the trigger set."
    elif drawdown < -0.10:
        lesson_type = "risk_failure"
        strategic = (
            f"The {action} exposure failed under severe drawdown ({drawdown:.6f}) with 20d reward {reward:.6f}. "
            f"The fragile state was: {'; '.join(triggers[:3])}."
        )
        do = "Reduce exposure or choose Hold/Underweight unless the close reclaims key moving averages and MACD/RSI stop deteriorating."
        avoid = f"Avoid repeating {action} when the same downside triggers and drawdown profile are present."
    else:
        lesson_type = "negative"
        strategic = (
            f"The {action} exposure generated weak/negative 20d reward ({reward:.6f}). "
            f"The state was not strong enough to justify the chosen exposure: {'; '.join(triggers[:3])}."
        )
        do = "Require a clearer confirmation signal, such as improving MACD plus price reclaiming SMA50, before increasing exposure."
        avoid = f"Avoid {action} when the trigger set remains mixed or contradicts the desired direction."

    return {
        "lesson_type": lesson_type,
        "strategic_analysis": strategic,
        "actionable_adjustment": f"Do: {do} Avoid: {avoid}",
        "trigger_conditions": triggers,
        "do": do,
        "avoid": avoid,
        "evidence_summary": {
            "symbol": payload.get("symbol"),
            "analysis_time": payload.get("analysis_time"),
            "action": action,
            "reward_20d": reward,
            "alpha_return": payload.get("alpha_return"),
            "max_drawdown_horizon": drawdown,
        },
    }


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


def llm_reflection(payload: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    if not HAS_LLM:
        raise RuntimeError("LLM dependencies are unavailable; use --reflection-mode rule_based.")
    config = DEFAULT_CONFIG.copy()
    client = create_llm_client(
        provider=config["llm_provider"],
        model=model or config["quick_think_llm"],
        base_url=config.get("backend_url"),
        temperature=0.0,
    )
    llm = client.get_llm()
    system_text = (
        "You are the MeMo Trajectory Reflection module for a trading agent. "
        "Generate one actionable memory from the supplied historical trajectory. "
        "You must be specific. Do not produce generic advice. Return JSON only."
    )
    user_text = (
        "Strategic State View and outcome:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n\n"
        "Return JSON with exactly these fields:\n"
        "lesson_type: positive | negative | risk_failure\n"
        "strategic_analysis: 2-3 sentences explaining why this state caused the result\n"
        "actionable_adjustment: 2-3 sentences with concrete trading adjustment\n"
        "trigger_conditions: array of at least 3 exact observable conditions using indicators, price levels, action, reward, drawdown, or news/macro clues\n"
        "do: one concrete instruction\n"
        "avoid: one concrete anti-pattern\n"
        "evidence_summary: object with symbol, date, action, reward_20d, alpha_return, max_drawdown_horizon\n\n"
        "Hard rules:\n"
        "- Do NOT say only 'be careful', 'monitor risks', 'consider macro', or similar generic text.\n"
        "- Every memory must include exact observable triggers such as RSI/MACD/SMA/price/volume/reward/drawdown/action/news.\n"
        "- If the evidence is weak, say exactly what confirmation should be required before changing exposure.\n"
    )
    response = llm.invoke([SystemMessage(content=system_text), HumanMessage(content=user_text)])
    parsed = parse_json_object(str(getattr(response, "content", response)))
    if not parsed:
        raise RuntimeError("LLM reflection did not return parseable JSON.")
    return parsed


def quality_gate(candidate: dict[str, Any]) -> tuple[bool, float, list[str]]:
    flags = []
    text = " ".join(
        str(candidate.get(k, "")) for k in ["strategic_analysis", "actionable_adjustment", "do", "avoid"]
    ).lower()
    triggers = candidate.get("trigger_conditions") or []
    if not isinstance(triggers, list):
        triggers = []

    if len(triggers) < 2:
        flags.append("too_few_trigger_conditions")
    if any(phrase in text for phrase in GENERIC_PHRASES):
        flags.append("contains_generic_phrase")
    trigger_text = " ".join(str(t).lower() for t in triggers)
    if not any(term in trigger_text for term in INDICATOR_TERMS):
        flags.append("missing_observable_trading_terms")
    if len(str(candidate.get("do", ""))) < 25:
        flags.append("do_instruction_too_short")
    if len(str(candidate.get("avoid", ""))) < 25:
        flags.append("avoid_instruction_too_short")

    score = 0.55
    score += min(len(triggers), 5) * 0.06
    score += 0.10 if not any(phrase in text for phrase in GENERIC_PHRASES) else -0.20
    score += 0.10 if any(term in trigger_text for term in INDICATOR_TERMS) else -0.20
    score += 0.05 if len(str(candidate.get("do", ""))) >= 40 else 0.0
    score += 0.05 if len(str(candidate.get("avoid", ""))) >= 40 else 0.0
    score = max(0.0, min(0.98, score))
    return len(flags) == 0, score, flags


def build_memory_record(
    *,
    args: argparse.Namespace,
    reward: dict[str, Any],
    traj: dict[str, Any],
    candidate: dict[str, Any],
    quality_score: float,
    quality_flags: list[str],
    payload: dict[str, Any],
    extraction_method: str,
    now: str,
) -> dict[str, Any]:
    reward_id = reward["reward_id"]
    traj_id = reward["trajectory_id"]
    memory_id = f"mem_{args.memory_bank_version}_{reward_id}"
    features = payload.get("context_features") or {}
    lesson = (
        f"Strategic analysis: {candidate.get('strategic_analysis', '')} "
        f"Actionable adjustment: {candidate.get('actionable_adjustment', '')}"
    ).strip()
    return {
        "memory_id": memory_id,
        "memory_bank_version": args.memory_bank_version,
        "source_tournament_id": args.tournament_id,
        "source_score_scope_id": args.score_scope_id,
        "source_generation_id": reward.get("generation_id"),
        "source_prompt_set_id": reward.get("prompt_set_id"),
        "source_trajectory_id": traj_id,
        "source_reward_id": reward_id,
        "source_time": traj.get("analysis_time"),
        "symbol": reward.get("symbol"),
        "agent_role": "trader",
        "lesson_type": candidate.get("lesson_type", "negative"),
        "market_regime": infer_regime(features),
        "situation_summary": (
            f"{reward.get('symbol')} {str(traj.get('analysis_time', ''))[:10]} action={reward.get('final_action')} "
            f"reward_20d={float(reward.get('total_reward') or 0.0):.6f}."
        ),
        "lesson": lesson,
        "strategic_analysis": candidate.get("strategic_analysis"),
        "actionable_adjustment": candidate.get("actionable_adjustment"),
        "trigger_conditions": candidate.get("trigger_conditions") or [],
        "do": candidate.get("do"),
        "avoid": candidate.get("avoid"),
        "use_when": candidate.get("trigger_conditions") or [],
        "avoid_when": [candidate.get("avoid")] if candidate.get("avoid") else [],
        "evidence_summary": candidate.get("evidence_summary") or payload,
        "quality_score": float(quality_score),
        "quality_flags": quality_flags,
        "reward_20d": float(reward.get("total_reward") or 0.0),
        "max_drawdown_horizon": reward.get("max_drawdown_horizon"),
        "final_action": reward.get("final_action"),
        "extraction_method": extraction_method,
        "memory_version": args.memory_bank_version,
        "created_at": now,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract MeMo memory lessons from scored baseline rewards.")
    parser.add_argument("--tournament-id", required=True)
    parser.add_argument("--score-scope-id", default=None)
    parser.add_argument("--memory-bank-version", default="mb_2022_gen0_v1")
    parser.add_argument("--data-mode", default="offline_materialized")
    parser.add_argument("--comparison-group", default="baseline_no_memory")
    parser.add_argument("--source-memory-bank-version", default="none")
    parser.add_argument("--context-policy-id", default="ctx_paper_aligned_v1")
    parser.add_argument("--max-memories", type=int, default=200)
    parser.add_argument("--reflection-mode", choices=["rule_based", "llm"], default="rule_based")
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--replace-version", action="store_true")
    args = parser.parse_args()

    trajectories_path = DATA_DIR / "trajectories" / "workflow_trajectories.jsonl"
    rewards_path = DATA_DIR / "rewards" / "trajectory_rewards.jsonl"
    scores_path = DATA_DIR / "tournament_scores" / "tournament_scores.jsonl"
    inputs_path = DATA_DIR / "materialized_inputs" / f"inputs_{args.context_policy_id}.jsonl"
    memory_path = DATA_DIR / "memory_bank" / "memo_memory_bank.jsonl"
    memory_manifest = DATA_DIR / "memory_bank" / "manifest.json"

    trajectories = load_jsonl(trajectories_path)
    rewards = load_jsonl(rewards_path)
    scores = load_jsonl(scores_path)
    inputs = load_jsonl(inputs_path)
    existing_memories = load_jsonl(memory_path) if memory_path.exists() else {}

    if args.replace_version:
        kept = [m for m in existing_memories.values() if m.get("memory_bank_version") != args.memory_bank_version]
        rewrite_jsonl(memory_path, kept)
        existing_memories = {m["memory_id"]: m for m in kept if m.get("memory_id")}
        logger.info("Removed existing memories for version %s before rebuild.", args.memory_bank_version)

    scoped_scores = [
        s
        for s in scores.values()
        if s.get("tournament_id") == args.tournament_id
        and (args.score_scope_id is None or s.get("score_scope_id") == args.score_scope_id)
    ]
    score_by_prompt = {s.get("prompt_set_id"): s for s in scoped_scores}

    selected_trajectory_ids = set()
    for traj_id, traj in trajectories.items():
        if traj.get("tournament_id") != args.tournament_id:
            continue
        if traj.get("run_status") != "succeeded":
            continue
        if args.data_mode and traj.get("data_mode") != args.data_mode:
            continue
        if args.comparison_group and comparison_group_for(traj) != args.comparison_group:
            continue
        if args.source_memory_bank_version and memory_bank_version_for(traj) != args.source_memory_bank_version:
            continue
        selected_trajectory_ids.add(traj_id)

    filtered_rewards = [
        r
        for r in rewards.values()
        if r.get("tournament_id") == args.tournament_id
        and r.get("trajectory_id") in selected_trajectory_ids
        and r.get("total_reward") is not None
    ]
    selected_rewards = selected_rewards_by_extremes(filtered_rewards, args.max_memories)
    logger.info("Selected %d rewards from %d trajectories for memory extraction.", len(selected_rewards), len(selected_trajectory_ids))

    added = 0
    removed_generic = 0
    reflection_errors = 0
    now = pd.Timestamp.utcnow().isoformat()
    for reward in selected_rewards:
        traj = trajectories.get(reward.get("trajectory_id"))
        if not traj:
            continue
        input_data = inputs.get(traj.get("input_id"), {})
        payload = build_reflection_payload(reward, traj, input_data, score_by_prompt)
        try:
            if args.reflection_mode == "llm":
                candidate = llm_reflection(payload, args.llm_model)
                extraction_method = "llm_reflection_v0.1"
            else:
                candidate = rule_based_reflection(payload)
                extraction_method = "rule_based_reflection_v0.3"
        except Exception as exc:
            reflection_errors += 1
            logger.warning("Reflection failed for %s: %s; using rule-based fallback.", reward.get("reward_id"), exc)
            candidate = rule_based_reflection(payload)
            extraction_method = "rule_based_reflection_v0.3_fallback"

        passed, quality_score, quality_flags = quality_gate(candidate)
        if not passed:
            removed_generic += 1
            continue

        memory_record = build_memory_record(
            args=args,
            reward=reward,
            traj=traj,
            candidate=candidate,
            quality_score=quality_score,
            quality_flags=quality_flags,
            payload=payload,
            extraction_method=extraction_method,
            now=now,
        )
        upsert_jsonl(memory_path, "memory_id", memory_record)
        existing_memories[memory_record["memory_id"]] = memory_record
        added += 1

    logger.info("Added/updated %d memories; removed %d generic candidates; reflection_errors=%d", added, removed_generic, reflection_errors)

    manifest = {
        "dataset_version": args.memory_bank_version,
        "count": len(existing_memories),
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "source_tournament_id": args.tournament_id,
        "source_score_scope_id": args.score_scope_id,
        "data_mode": args.data_mode,
        "comparison_group": args.comparison_group,
        "source_memory_bank_version": args.source_memory_bank_version,
        "reflection_mode": args.reflection_mode,
        "quality_gate": "specific_actionable_v0.1",
        "removed_generic_candidates": removed_generic,
        "reflection_errors": reflection_errors,
    }
    with open(memory_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()