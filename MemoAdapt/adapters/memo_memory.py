"""MeMo memory retrieval and formatting helpers for offline tournament runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def load_memory_policy(path: Path, policy_id: str) -> dict[str, Any]:
    if not path.exists():
        return {"memory_policy_id": policy_id, "top_k_memories": 0}
    with open(path, "r", encoding="utf-8") as f:
        policies = json.load(f)
    if isinstance(policies, list):
        for policy in policies:
            if policy.get("memory_policy_id") == policy_id:
                return policy
    elif isinstance(policies, dict):
        return policies.get(policy_id, {"memory_policy_id": policy_id, "top_k_memories": 0})
    return {"memory_policy_id": policy_id, "top_k_memories": 0}


def load_memory_bank(path: Path, memory_bank_version: str) -> list[dict[str, Any]]:
    if memory_bank_version in (None, "", "none"):
        return []
    return [
        row
        for row in load_jsonl_records(path)
        if row.get("memory_bank_version") == memory_bank_version
        or row.get("memory_version") == memory_bank_version
    ]


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_simple_regime(input_data: dict[str, Any]) -> str:
    latest = input_data.get("latest_market_snapshot") or {}
    tech = input_data.get("technical_snapshot") or {}
    close = _float_or_none(latest.get("close") or tech.get("close"))
    sma50 = _float_or_none(tech.get("sma_50") or tech.get("close_50_sma"))
    sma200 = _float_or_none(tech.get("sma_200") or tech.get("close_200_sma"))
    macd = _float_or_none(tech.get("macd"))
    rsi = _float_or_none(tech.get("rsi") or tech.get("rsi_14"))

    bearish_votes = 0
    bullish_votes = 0
    if close is not None and sma50 is not None:
        bearish_votes += int(close < sma50)
        bullish_votes += int(close >= sma50)
    if close is not None and sma200 is not None:
        bearish_votes += int(close < sma200)
        bullish_votes += int(close >= sma200)
    if macd is not None:
        bearish_votes += int(macd < 0)
        bullish_votes += int(macd >= 0)
    if rsi is not None:
        bearish_votes += int(rsi < 45)
        bullish_votes += int(rsi > 55)

    if bearish_votes >= 2:
        return "bearish_momentum"
    if bullish_votes >= 2:
        return "bullish_momentum"
    return "mixed_regime"


def memory_score(memory: dict[str, Any], symbol: str, regime: str, policy: dict[str, Any]) -> float:
    score = float(memory.get("quality_score") or 0.0)
    if memory.get("symbol") == symbol and policy.get("same_symbol_boost", False):
        score += 0.75
    if memory.get("market_regime") == regime:
        score += 0.35
    if memory.get("lesson_type") in {"risk_failure", "negative"}:
        score += 0.05
    reward = abs(float(memory.get("reward_20d") or 0.0))
    score += min(reward, 0.25)
    return score


def retrieve_memories_for_context(
    *,
    input_data: dict[str, Any],
    symbol: str,
    memories: list[dict[str, Any]],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    top_k = int(policy.get("top_k_memories") or 0)
    if top_k <= 0 or not memories:
        return []

    regime = infer_simple_regime(input_data)
    candidates = []
    for memory in memories:
        if policy.get("agent_role_filter", True) and memory.get("agent_role") not in (None, "trader"):
            continue
        if policy.get("same_regime_required", False) and memory.get("market_regime") != regime:
            continue
        candidates.append(memory)

    candidates.sort(key=lambda m: memory_score(m, symbol, regime, policy), reverse=True)
    return candidates[:top_k]


def format_retrieved_memories(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return ""
    lines = [
        "## MeMo Retrieved Lessons",
        "Use these lessons only as situational prior experience for the final portfolio decision.",
        "Do not treat them as market evidence, and do not assume a past year will repeat exactly.",
        "Current point-in-time evidence and current portfolio state have priority.",
    ]
    for i, memory in enumerate(memories, start=1):
        triggers = memory.get("trigger_conditions") or memory.get("use_when") or []
        avoids = memory.get("avoid_when") or []
        lesson = memory.get("lesson") or memory.get("content") or memory.get("situation_summary") or ""
        do_text = memory.get("do") or memory.get("recommended_adjustment") or memory.get("better_action") or ""
        lines.extend(
            [
                f"### Memory {i}: {memory.get('lesson_type', 'lesson')} / {memory.get('symbol', 'ANY')} / {memory.get('market_regime', 'unknown')}",
                "Interpretation: situational analogy only; use when the current setup shares the trigger conditions.",
                f"Trigger conditions: {json.dumps(triggers, ensure_ascii=False)}",
                f"Lesson: {lesson}",
                f"Do: {do_text}",
                f"Avoid: {json.dumps(avoids, ensure_ascii=False)}",
            ]
        )
    return "\n".join(lines)
