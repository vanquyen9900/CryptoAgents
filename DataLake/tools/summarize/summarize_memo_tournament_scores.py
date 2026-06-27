"""Summarize MeMo tournament score rows.

Usage:
    python DataLake/tools/summarize/summarize_memo_tournament_scores.py --tournament-id tour_2022_gen0
    python DataLake/tools/summarize/summarize_memo_tournament_scores.py --score-scope-id offline_baseline_20220301
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DATALAKE_DIR = Path(__file__).resolve().parents[2]
SCORES_PATH = DATALAKE_DIR / "data" / "memo_adaptation" / "tournament_scores" / "tournament_scores.jsonl"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize MeMo tournament score rows.")
    parser.add_argument("--tournament-id", default=None)
    parser.add_argument("--generation-id", default=None)
    parser.add_argument("--score-scope-id", default=None)
    parser.add_argument("--data-mode", default=None)
    parser.add_argument("--comparison-group", default=None)
    parser.add_argument("--memory-bank-version", default=None)
    parser.add_argument("--score-method", default=None)
    args = parser.parse_args()

    rows = load_jsonl(SCORES_PATH)

    def keep(row: dict[str, Any]) -> bool:
        if args.tournament_id and row.get("tournament_id") != args.tournament_id:
            return False
        if args.generation_id and row.get("generation_id") != args.generation_id:
            return False
        if args.score_scope_id and row.get("score_scope_id") != args.score_scope_id:
            return False
        if args.data_mode and row.get("data_mode") != args.data_mode:
            return False
        if args.comparison_group and row.get("comparison_group") != args.comparison_group:
            return False
        if args.memory_bank_version and row.get("memory_bank_version") != args.memory_bank_version:
            return False
        if args.score_method and row.get("score_method", "financial") != args.score_method:
            return False
        return True

    selected = [row for row in rows if keep(row)]
    selected.sort(key=lambda row: (row.get("rank") is None, row.get("rank", 999), -float(row.get("total_score", 0.0))))

    print("MeMo tournament score summary")
    print("=" * 34)
    print(f"Rows: {len(selected)}")
    for row in selected:
        if row.get("score_method") == "trueskill":
            print(
                f"rank={row.get('rank')} "
                f"prompt={row.get('prompt_set_id')} "
                f"mu={float(row.get('trueskill_mu', 0.0)):.4f} "
                f"sigma={float(row.get('trueskill_sigma', 0.0)):.4f} "
                f"win_rate={float(row.get('match_win_rate', 0.0)):.4f} "
                f"top_rate={float(row.get('match_top_rate', row.get('match_win_rate', 0.0))):.4f} "
                f"matches={row.get('matches_played')} "
                f"financial={float(row.get('financial_score', 0.0)):.8f} "
                f"1d={float(row.get('mean_reward_1d', 0.0)):.8f} "
                f"5d={float(row.get('mean_reward_5d', 0.0)):.8f} "
                f"20d={float(row.get('mean_reward_20d', 0.0)):.8f} "
                f"scope={row.get('score_scope_id')}"
            )
        else:
            print(
                f"rank={row.get('rank')} "
                f"prompt={row.get('prompt_set_id')} "
                f"score={float(row.get('total_score', 0.0)):.8f} "
                f"episodes={row.get('episodes_count')} "
                f"1d={float(row.get('mean_reward_1d', 0.0)):.8f} "
                f"5d={float(row.get('mean_reward_5d', 0.0)):.8f} "
                f"20d={float(row.get('mean_reward_20d', 0.0)):.8f} "
                f"scope={row.get('score_scope_id')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
