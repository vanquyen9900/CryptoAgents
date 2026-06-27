import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

DATALAKE_DIR = Path(__file__).resolve().parents[2]


EXPECTED_GROUPS = {
    "test_q1_2024_baseline_no_memory": {
        "label": "Arm A baseline no memory",
        "must_have_memory_version": {"none", None, ""},
        "must_not_contain_2022_memory": True,
    },
    "test_q1_2024_2022_memory_weekly_learning": {
        "label": "Arm B 2022 memory + weekly learning",
        "must_contain_2022_memory": True,
    },
    "test_q1_2024_weekly_learning_only": {
        "label": "Arm C weekly learning only",
        "must_not_contain_2022_memory": True,
    },
}

EXPECTED_TRAJECTORY_GROUPS = {
    "test_q1_2024_baseline_no_memory",
    "test_q1_2024_2022_memory_weekly_learning",
}


REQUIRED_METRIC_FIELDS = ["cr_pct", "arr_pct", "sharpe", "mdd_pct"]


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


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    value = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_finite_or_null(value):
    if value is None:
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


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


def load_group_metrics(portfolio_dir: Path, group: str):
    paths = [
        portfolio_dir / group / "portfolio_metrics.jsonl",
        portfolio_dir / f"{group}_portfolio_metrics.jsonl",
        portfolio_dir / "portfolio_metrics.jsonl",
    ]
    rows = []
    for path in paths:
        for row in load_jsonl(path):
            if row.get("comparison_group") in (None, "", group) or path.name != "portfolio_metrics.jsonl":
                rows.append(row)
    if rows and paths[-1].exists():
        rows = [r for r in rows if r.get("comparison_group") in (None, "", group)]
    return rows


def load_group_equity_curves(portfolio_dir: Path, group: str):
    paths = [
        portfolio_dir / group / "equity_curves.jsonl",
        portfolio_dir / f"{group}_equity_curves.jsonl",
        portfolio_dir / "equity_curves.jsonl",
    ]
    rows = []
    for path in paths:
        for row in load_jsonl(path):
            if row.get("comparison_group") in (None, "", group) or path.name != "equity_curves.jsonl":
                rows.append(row)
    if rows and paths[-1].exists():
        rows = [r for r in rows if r.get("comparison_group") in (None, "", group)]
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Contract tests for paper-style Q1-2024 MeMo portfolio evaluation artifacts."
    )
    parser.add_argument("--data-dir", default=str(DATALAKE_DIR / "data_test_2024_q1"))
    parser.add_argument("--tournament-id", default="tour_2024_q1_eval")
    parser.add_argument("--start-date", default="2024-01-02")
    parser.add_argument("--end-date", default="2024-03-29")
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "AMZN", "GOOGL"])
    parser.add_argument(
        "--prompt-set-ids",
        nargs="+",
        default=["ps_default_v1", "ps_risk_aware_v1", "ps_macro_defensive_v1"],
    )
    args = parser.parse_args()

    contract = Contract()
    data_dir = Path(args.data_dir)
    artifact_root = find_artifact_root(data_dir)
    portfolio_dir = artifact_root / "portfolio_evaluation"
    trajectory_path = artifact_root / "trajectories" / "workflow_trajectories.jsonl"
    memory_path = artifact_root / "memory_bank" / "memo_memory_bank.jsonl"

    print("Portfolio evaluation contract tests")
    print(f"data_dir={data_dir}")
    print(f"artifact_root={artifact_root}")
    print(f"tournament_id={args.tournament_id}")

    trajectories = [
        row
        for row in load_jsonl(trajectory_path)
        if row.get("tournament_id") == args.tournament_id
    ]
    contract.check("Q1 trajectories exist", len(trajectories) > 0, f"{len(trajectories)} rows")

    groups_seen = Counter(row.get("comparison_group") for row in trajectories)
    for group in EXPECTED_TRAJECTORY_GROUPS:
        contract.check(
            f"trajectories exist for {group}",
            groups_seen[group] > 0,
            f"{groups_seen[group]} rows",
        )

    symbols_seen = defaultdict(set)
    prompts_seen = defaultdict(set)
    for row in trajectories:
        group = row.get("comparison_group")
        if group in EXPECTED_TRAJECTORY_GROUPS:
            symbols_seen[group].add(row.get("symbol"))
            prompts_seen[group].add(row.get("prompt_set_id"))

    for group in EXPECTED_TRAJECTORY_GROUPS:
        contract.check(
            f"{group} covers all symbols",
            set(args.symbols).issubset(symbols_seen[group]),
            f"seen={sorted(symbols_seen[group])}",
        )
        contract.check(
            f"{group} covers expected prompt sets",
            set(args.prompt_set_ids).issubset(prompts_seen[group]),
            f"seen={sorted(prompts_seen[group])}",
        )

    arm_a_rows = [r for r in trajectories if r.get("comparison_group") == "test_q1_2024_baseline_no_memory"]
    contract.check(
        "Arm A uses no memory",
        all(r.get("memory_bank_version") in {"none", None, ""} for r in arm_a_rows),
        f"{len(arm_a_rows)} rows checked",
    )

    memories = load_jsonl(memory_path)
    arm_c_memories = [
        m
        for m in memories
        if m.get("memory_bank_version") == "mb_q1_2024_weekly_only_v1"
    ]
    contract.check(
        "Arm C memory has no 2022 source IDs",
        all("2022" not in json.dumps(m, ensure_ascii=False) for m in arm_c_memories),
        f"{len(arm_c_memories)} memories checked",
    )

    for group in EXPECTED_GROUPS:
        metrics = load_group_metrics(portfolio_dir, group)
        contract.check(f"portfolio metrics exist for {group}", len(metrics) > 0, f"{len(metrics)} rows")

        metric_symbols = {m.get("symbol") or m.get("Symbol") for m in metrics}
        contract.check(
            f"{group} metrics cover all symbols",
            set(args.symbols).issubset(metric_symbols),
            f"seen={sorted(x for x in metric_symbols if x)}",
        )

        bh_rows = [
            m
            for m in metrics
            if str(m.get("model") or m.get("Model") or "").lower() in {"b&h", "buy_and_hold", "buy-and-hold"}
        ]
        bh_symbols = {m.get("symbol") or m.get("Symbol") for m in bh_rows}
        contract.check(
            f"{group} includes B&H for all symbols",
            set(args.symbols).issubset(bh_symbols),
            f"seen={sorted(x for x in bh_symbols if x)}",
        )

        finite = True
        missing_fields = []
        for row in metrics:
            for field in REQUIRED_METRIC_FIELDS:
                if field not in row:
                    missing_fields.append(field)
                    finite = False
                elif not is_finite_or_null(row.get(field)):
                    finite = False
        contract.check(
            f"{group} metric fields are present and finite/null",
            finite,
            f"missing={sorted(set(missing_fields))}" if missing_fields else "",
        )

        curves = load_group_equity_curves(portfolio_dir, group)
        curve_symbols = {r.get("symbol") for r in curves}
        contract.check(
            f"{group} equity curves cover all symbols",
            set(args.symbols).issubset(curve_symbols),
            f"rows={len(curves)}",
        )

        values_positive = all(
            r.get("portfolio_value") is None or float(r.get("portfolio_value")) >= 0
            for r in curves
        )
        contract.check(f"{group} equity curve values are non-negative", values_positive)

    weekly_lesson_rows = [
        m
        for m in memories
        if str(m.get("memory_bank_version", "")).startswith("mb_q1_2024_")
    ]
    leakage_free = True
    for memory in weekly_lesson_rows:
        created_at = parse_dt(memory.get("created_at") or memory.get("available_at"))
        visible_from = parse_dt(memory.get("visible_from") or memory.get("available_from"))
        week_end = parse_dt(memory.get("week_end") or memory.get("source_week_end"))
        if week_end and visible_from and visible_from <= week_end:
            leakage_free = False
        if week_end and created_at and created_at < week_end:
            leakage_free = False
    contract.check(
        "weekly lessons become visible only after source week closes",
        leakage_free,
        f"{len(weekly_lesson_rows)} weekly memories checked",
    )

    report_paths = [portfolio_dir / "summary_report.md"]
    report_paths.extend(portfolio_dir.glob("**/summary_report.md"))
    alt_report_path = DATALAKE_DIR / "reports" / "q1_2024_portfolio_evaluation_report.md"
    contract.check(
        "portfolio summary report exists",
        any(path.exists() for path in report_paths) or alt_report_path.exists(),
        f"checked {len(report_paths)} portfolio paths and {alt_report_path}",
    )

    contract.finish()


if __name__ == "__main__":
    main()
