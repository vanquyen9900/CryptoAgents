import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

DATALAKE_DIR = Path(__file__).resolve().parents[2]


EXPECTED_GROUPS = [
    "test_q1_2024_baseline_no_memory",
    "test_q1_2024_2022_memory_weekly_learning",
]


MOCK_TRAJECTORY_ID_RE = re.compile(r"^traj_\d+$", re.IGNORECASE)
MOCK_TEXT_MARKERS = [
    "mock pipeline",
    "mock market report",
    "mock output",
    "dummy",
    "placeholder",
    "synthetic trajectory",
]


def load_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AssertionError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def text_blob(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True).lower()


def find_artifact_root(data_dir: Path):
    candidates = [
        data_dir / "memo_adaptation",
        data_dir / "memo_adaptation_test_2024_q1",
        data_dir,
    ]
    for candidate in candidates:
        if (candidate / "trajectories").exists() or (candidate / "portfolio_evaluation").exists():
            return candidate
    return candidates[0]


class Contract:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, name, condition, details=""):
        if condition:
            print(f"[PASS] {name}{' - ' + details if details else ''}")
            self.passed += 1
        else:
            print(f"[FAIL] {name}{' - ' + details if details else ''}")
            self.failed += 1

    def finish(self):
        print("\n--- Summary ---")
        print(f"PASS={self.passed} FAIL={self.failed}")
        if self.failed:
            raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Contract tests that reject mock/demo Q1-2024 portfolio evaluation artifacts."
    )
    parser.add_argument("--data-dir", default=str(DATALAKE_DIR / "data_test_2024_q1"))
    parser.add_argument("--tournament-id", default="tour_2024_q1_eval")
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "AMZN", "GOOGL"])
    parser.add_argument(
        "--prompt-set-ids",
        nargs="+",
        default=["ps_default_v1", "ps_risk_aware_v1", "ps_macro_defensive_v1"],
    )
    parser.add_argument(
        "--min-rows-per-group",
        type=int,
        default=180,
        help="Minimum real trajectory rows expected per comparison group.",
    )
    parser.add_argument(
        "--allow-failed-runs",
        action="store_true",
        help="Allow failed run_status rows, but still reject null/mock status.",
    )
    args = parser.parse_args()

    contract = Contract()
    data_dir = Path(args.data_dir)
    artifact_root = find_artifact_root(data_dir)
    trajectory_path = artifact_root / "trajectories" / "workflow_trajectories.jsonl"
    memory_path = artifact_root / "memory_bank" / "memo_memory_bank.jsonl"
    portfolio_dir = artifact_root / "portfolio_evaluation"
    global_report_path = DATALAKE_DIR / "reports" / "q1_2024_portfolio_evaluation_report.md"

    print("Q1 real artifact contract tests")
    print(f"data_dir={data_dir}")
    print(f"artifact_root={artifact_root}")
    print(f"tournament_id={args.tournament_id}")

    trajectories = [
        row
        for row in load_jsonl(trajectory_path)
        if row.get("tournament_id") == args.tournament_id
    ]
    contract.check("real trajectory file exists", trajectory_path.exists(), str(trajectory_path))
    contract.check("trajectories exist for tournament", len(trajectories) > 0, f"{len(trajectories)} rows")

    groups = Counter(row.get("comparison_group") for row in trajectories)
    for group in EXPECTED_GROUPS:
        contract.check(
            f"{group} has enough trajectory rows",
            groups[group] >= args.min_rows_per_group,
            f"{groups[group]} rows",
        )

    mock_ids = [row.get("trajectory_id") for row in trajectories if MOCK_TRAJECTORY_ID_RE.match(str(row.get("trajectory_id", "")))]
    contract.check(
        "trajectory IDs are not mock-style traj_N",
        len(mock_ids) == 0,
        f"mock_id_count={len(mock_ids)} sample={mock_ids[:5]}",
    )

    missing_status = [row.get("trajectory_id") for row in trajectories if row.get("run_status") in {None, ""}]
    contract.check(
        "all trajectories have run_status",
        len(missing_status) == 0,
        f"missing_status_count={len(missing_status)} sample={missing_status[:5]}",
    )

    if args.allow_failed_runs:
        acceptable_statuses = {"succeeded", "failed", "skipped"}
    else:
        acceptable_statuses = {"succeeded"}
    bad_statuses = [
        (row.get("trajectory_id"), row.get("run_status"))
        for row in trajectories
        if row.get("run_status") not in acceptable_statuses
    ]
    contract.check(
        f"trajectory statuses are {sorted(acceptable_statuses)}",
        len(bad_statuses) == 0,
        f"bad_status_count={len(bad_statuses)} sample={bad_statuses[:5]}",
    )

    mock_marker_rows = []
    for row in trajectories:
        blob = text_blob(row)
        if any(marker in blob for marker in MOCK_TEXT_MARKERS):
            mock_marker_rows.append(row.get("trajectory_id"))
    contract.check(
        "trajectories do not contain mock/demo text markers",
        len(mock_marker_rows) == 0,
        f"mock_marker_count={len(mock_marker_rows)} sample={mock_marker_rows[:5]}",
    )

    symbols_seen = defaultdict(set)
    prompts_seen = defaultdict(set)
    decisions_seen = defaultdict(Counter)
    for row in trajectories:
        group = row.get("comparison_group")
        if group not in EXPECTED_GROUPS:
            continue
        symbols_seen[group].add(row.get("symbol"))
        prompts_seen[group].add(row.get("prompt_set_id"))
        decision = row.get("agent_outputs", {}).get("final_trade_decision")
        decisions_seen[group][str(decision).strip().upper()] += 1

    for group in EXPECTED_GROUPS:
        contract.check(
            f"{group} covers requested symbols",
            set(args.symbols).issubset(symbols_seen[group]),
            f"seen={sorted(symbols_seen[group])}",
        )
        contract.check(
            f"{group} covers requested prompts",
            set(args.prompt_set_ids).issubset(prompts_seen[group]),
            f"seen={sorted(prompts_seen[group])}",
        )
        non_empty_decisions = sum(count for action, count in decisions_seen[group].items() if action not in {"", "NONE", "NULL"})
        contract.check(
            f"{group} has non-empty final decisions",
            non_empty_decisions == groups[group],
            f"decision_counts={dict(decisions_seen[group])}",
        )
        contract.check(
            f"{group} decisions are not one-action-only",
            len([a for a, c in decisions_seen[group].items() if c > 0]) > 1,
            f"decision_counts={dict(decisions_seen[group])}",
        )

    memories = load_jsonl(memory_path)
    arm_b_seed_or_weekly = [
        row
        for row in memories
        if row.get("memory_bank_version") in {
            "mb_q1_2024_seed2022_weekly_v1",
            "mb_q1_2024_2022_memory_weekly_learning_v1",
        }
    ]
    contract.check(
        "Arm B has Q1 weekly memory version, not only raw 2022 seed",
        len(arm_b_seed_or_weekly) > 0,
        f"{len(arm_b_seed_or_weekly)} rows",
    )

    arm_c_memories = [
        row
        for row in memories
        if row.get("memory_bank_version") == "mb_q1_2024_weekly_only_v1"
    ]
    arm_c_has_2022 = [row.get("memory_id") for row in arm_c_memories if "2022" in text_blob(row)]
    contract.check(
        "Arm C weekly-only memory contains no 2022 seed/source content",
        len(arm_c_has_2022) == 0,
        f"violations={arm_c_has_2022[:5]}",
    )

    report_paths = [global_report_path]
    report_paths.extend(portfolio_dir.glob("**/summary_report.md"))
    report_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore").lower() for path in report_paths if path.exists())
    contract.check("portfolio report exists", bool(report_text), f"checked {len(report_paths)} paths")
    contract.check(
        "portfolio report is not marked as mock",
        "mock pipeline" not in report_text and "generated by mock" not in report_text,
    )

    contract.finish()


if __name__ == "__main__":
    main()
