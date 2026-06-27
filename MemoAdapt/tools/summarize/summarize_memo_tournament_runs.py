"""Summarize MeMo tournament trajectory outputs and rough LLM quota usage.

Usage:
    python MemoAdapt/tools/summarize/summarize_memo_tournament_runs.py --tournament-id tour_2022_gen0
    python MemoAdapt/tools/summarize/summarize_memo_tournament_runs.py --data-mode offline_materialized --start-date 2022-03-01 --end-date 2022-03-01
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DATALAKE_DIR = Path(__file__).resolve().parents[2]
TRAJECTORIES_PATH = DATALAKE_DIR / "data" / "memo_adaptation" / "trajectories" / "workflow_trajectories.jsonl"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def first_nonempty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def comparison_group_for(row: dict[str, Any]) -> str:
    explicit = row.get("comparison_group")
    if explicit:
        return str(explicit)
    return "baseline_no_memory" if row.get("memory_policy_id") == "mem_none_v1" else "memory_enabled"


def memory_bank_version_for(row: dict[str, Any]) -> str:
    explicit = row.get("memory_bank_version")
    if explicit:
        return str(explicit)
    return "none" if row.get("memory_policy_id") == "mem_none_v1" else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize MeMo tournament trajectories.")
    parser.add_argument("--tournament-id", default=None)
    parser.add_argument("--generation-id", default=None)
    parser.add_argument("--data-mode", default=None)
    parser.add_argument("--comparison-group", default=None)
    parser.add_argument("--memory-bank-version", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--prompt-set-id", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--sample-chars", type=int, default=1200)
    args = parser.parse_args()

    rows = load_jsonl(TRAJECTORIES_PATH)

    def keep(row: dict[str, Any]) -> bool:
        if args.tournament_id and row.get("tournament_id") != args.tournament_id:
            return False
        if args.generation_id and row.get("generation_id") != args.generation_id:
            return False
        if args.data_mode and row.get("data_mode") != args.data_mode:
            return False
        if args.comparison_group and comparison_group_for(row) != args.comparison_group:
            return False
        if args.memory_bank_version and memory_bank_version_for(row) != args.memory_bank_version:
            return False
        if args.symbol and row.get("symbol") != args.symbol:
            return False
        if args.prompt_set_id and row.get("prompt_set_id") != args.prompt_set_id:
            return False
        date = str(row.get("analysis_time", ""))[:10]
        if args.start_date and date < args.start_date:
            return False
        if args.end_date and date > args.end_date:
            return False
        return True

    selected = [row for row in rows if keep(row)]
    statuses: dict[str, int] = {}
    data_modes: dict[str, int] = {}
    comparison_groups: dict[str, int] = {}
    memory_bank_versions: dict[str, int] = {}
    prompt_sets: dict[str, int] = {}
    symbols: dict[str, int] = {}
    llm_calls = 0
    input_tokens = 0
    output_tokens = 0
    token_rows = 0

    for row in selected:
        statuses[str(row.get("run_status"))] = statuses.get(str(row.get("run_status")), 0) + 1
        data_modes[str(row.get("data_mode", "unknown"))] = data_modes.get(str(row.get("data_mode", "unknown")), 0) + 1
        group = comparison_group_for(row)
        memory_version = memory_bank_version_for(row)
        comparison_groups[group] = comparison_groups.get(group, 0) + 1
        memory_bank_versions[memory_version] = memory_bank_versions.get(memory_version, 0) + 1
        prompt_sets[str(row.get("prompt_set_id"))] = prompt_sets.get(str(row.get("prompt_set_id")), 0) + 1
        symbols[str(row.get("symbol"))] = symbols.get(str(row.get("symbol")), 0) + 1
        llm_calls += int(row.get("llm_call_count") or 0)
        if row.get("input_tokens") is not None:
            input_tokens += int(row.get("input_tokens") or 0)
            token_rows += 1
        if row.get("output_tokens") is not None:
            output_tokens += int(row.get("output_tokens") or 0)

    print("MeMo tournament run summary")
    print("=" * 34)
    print(f"Rows: {len(selected)}")
    print(f"Statuses: {statuses}")
    print(f"Data modes: {data_modes}")
    print(f"Comparison groups: {comparison_groups}")
    print(f"Memory bank versions: {memory_bank_versions}")
    print(f"Symbols: {symbols}")
    print(f"Prompt sets: {prompt_sets}")
    print(f"LLM calls: {llm_calls}")
    print(f"Input tokens: {input_tokens}" + (" (estimated or provider-reported)" if token_rows else ""))
    print(f"Output tokens: {output_tokens}" + (" (estimated or provider-reported)" if token_rows else ""))
    print(f"Total tokens: {input_tokens + output_tokens}")

    sample = next((row for row in selected if row.get("run_status") == "succeeded"), selected[0] if selected else None)
    if sample:
        outputs = sample.get("agent_outputs", {})
        decision = first_nonempty(outputs.get("final_trade_decision"))
        report = first_nonempty(outputs.get("market_report"), outputs.get("investment_plan"))
        print("-" * 34)
        print(f"Sample trajectory: {sample.get('trajectory_id')}")
        print(f"Sample decision: {decision[:500]}")
        print("Sample report:")
        print(report[: args.sample_chars])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
