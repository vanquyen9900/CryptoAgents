"""Decision and position context for sequential offline portfolio experiments."""

from __future__ import annotations

import re
from typing import Any


ACTION_ORDER = ["Overweight", "Underweight", "Buy", "Sell", "Hold"]


def parse_action(text: Any) -> str:
    """Extract the portfolio action from a free-text decision."""
    if text is None:
        return ""
    value = str(text)
    rating_match = re.search(
        r"(?:rating|action|decision)\s*[:\-]\s*\**\s*([A-Za-z ]+)",
        value,
        re.IGNORECASE,
    )
    if rating_match:
        first_line = rating_match.group(1).strip().splitlines()[0]
        for action in ACTION_ORDER:
            if action.lower() in first_line.lower():
                return action
    for action in ACTION_ORDER:
        if re.search(rf"\b{action}\b", value, re.IGNORECASE):
            return action
    return ""


def exposure_after_action(action: str, previous_exposure: float) -> float:
    """Long/cash exposure model used by the Q1 paper-style evaluator."""
    normalized = parse_action(action)
    if normalized in {"Buy", "Overweight"}:
        return 1.0
    if normalized in {"Sell", "Underweight"}:
        return 0.0
    if normalized == "Hold":
        return previous_exposure
    return previous_exposure


def _shorten(text: Any, max_chars: int = 700) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def select_prior_trajectories(
    *,
    trajectories: list[dict[str, Any]],
    tournament_id: str,
    comparison_group: str,
    prompt_set_id: str,
    symbol: str,
    analysis_time: str,
) -> list[dict[str, Any]]:
    """Return prior same-arm/same-prompt/same-symbol trajectories only."""
    prior = []
    for row in trajectories:
        if row.get("tournament_id") != tournament_id:
            continue
        if row.get("comparison_group") != comparison_group:
            continue
        if row.get("prompt_set_id") != prompt_set_id:
            continue
        if row.get("symbol") != symbol:
            continue
        if row.get("run_status") != "succeeded":
            continue
        row_time = str(row.get("analysis_time", ""))
        if row_time and row_time < analysis_time:
            prior.append(row)
    prior.sort(key=lambda r: str(r.get("analysis_time", "")))
    return prior


def current_exposure_from_prior(prior_trajectories: list[dict[str, Any]]) -> float:
    """Replay prior decisions into the current long/cash exposure."""
    exposure = 0.0
    for row in prior_trajectories:
        decision = row.get("agent_outputs", {}).get("final_trade_decision", "")
        exposure = exposure_after_action(decision, exposure)
    return exposure


def format_decision_ledger_context(
    *,
    prior_trajectories: list[dict[str, Any]],
    current_exposure: float,
    max_entries: int = 5,
) -> str:
    """Render previous decisions for the final decision agent."""
    lines = [
        "## Current Portfolio State and Recent Decision Ledger",
        "This ledger contains only earlier decisions from the same symbol, prompt set, and experiment arm.",
        f"Current simulated exposure before today's decision: {current_exposure:.2f} (0.00=cash, 1.00=fully long)",
    ]
    if not prior_trajectories:
        lines.append("No prior same-symbol decisions in this experiment arm. Treat the portfolio as cash.")
        return "\n".join(lines)

    lines.append("Most recent prior decisions:")
    for row in reversed(prior_trajectories[-max_entries:]):
        outputs = row.get("agent_outputs", {})
        decision = outputs.get("final_trade_decision", "")
        rationale = (
            outputs.get("trader_plan")
            or outputs.get("investment_plan")
            or outputs.get("market_report")
            or ""
        )
        lines.extend(
            [
                f"- Date: {str(row.get('analysis_time', ''))[:10]}",
                f"  Action: {parse_action(decision) or _shorten(decision, 120)}",
                f"  Rationale/context: {_shorten(rationale)}",
                f"  Source trajectory: {row.get('trajectory_id', '')}",
            ]
        )
    return "\n".join(lines)


def build_decision_ledger_context(
    *,
    trajectories: list[dict[str, Any]],
    tournament_id: str,
    comparison_group: str,
    prompt_set_id: str,
    symbol: str,
    analysis_time: str,
    max_entries: int = 5,
) -> tuple[str, float, list[str]]:
    """Build final-decision-only context and return source trajectory IDs."""
    prior = select_prior_trajectories(
        trajectories=trajectories,
        tournament_id=tournament_id,
        comparison_group=comparison_group,
        prompt_set_id=prompt_set_id,
        symbol=symbol,
        analysis_time=analysis_time,
    )
    exposure = current_exposure_from_prior(prior)
    context = format_decision_ledger_context(
        prior_trajectories=prior,
        current_exposure=exposure,
        max_entries=max_entries,
    )
    return context, exposure, [row.get("trajectory_id", "") for row in prior[-max_entries:]]
