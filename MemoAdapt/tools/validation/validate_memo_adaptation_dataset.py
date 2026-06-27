"""Strict validation for the MeMo adaptation dataset.

Usage:
    python MemoAdapt/tools/validation/validate_memo_adaptation_dataset.py
    python MemoAdapt/tools/validation/validate_memo_adaptation_dataset.py --max-jsonl-rows 0

This validator is intentionally standalone. It validates the dataset layer used
to prepare the combined MeMo + TradingAgents adaptation dataset:

- materialized point-in-time inputs
- trading episodes
- context/memory/prompt policies
- adaptation run plan

The checks are strict about temporal leakage. Labels, future returns, rewards,
and future benchmark values must never appear inside materialized agent inputs.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DATALAKE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = DATALAKE_DIR / "data"
ADAPT_DIR = DATA_DIR / "memo_adaptation"

MVP_SYMBOLS = {"AAPL", "AMZN", "GOOGL"}
DATASET_START = pd.Timestamp("2019-01-01T00:00:00Z")
DATASET_END = pd.Timestamp("2023-12-31T23:59:59Z")

HORIZONS = {"1d", "5d", "20d"}
ALLOWED_COVERAGE = {"ok", "partial", "missing", "unknown", "unknown_known_time"}
ALLOWED_RUN_STATUS = {"planned", "succeeded", "failed", "skipped"}

LEAKAGE_KEYS = {
    "label",
    "labels",
    "label_direction",
    "label_refs",
    "labels_ref",
    "future_return",
    "benchmark_return",
    "alpha_return",
    "max_drawdown_horizon",
    "horizon_days",
    "reward",
    "rewards",
    "reward_id",
    "total_reward",
    "directional_score",
    "alpha_score",
    "risk_penalty",
    "final_action",
}


@dataclass
class CheckResult:
    level: str
    name: str
    detail: str = ""


class Validator:
    def __init__(self, max_jsonl_rows: int = 0, verbose: bool = True):
        self.max_jsonl_rows = max_jsonl_rows
        self.verbose = verbose
        self.results: list[CheckResult] = []
        self.inputs: list[dict[str, Any]] = []
        self.episodes: list[dict[str, Any]] = []
        self.context_policies: list[dict[str, Any]] = []
        self.memory_policies: list[dict[str, Any]] = []
        self.prompt_variants: list[dict[str, Any]] = []
        self.adaptation_runs: list[dict[str, Any]] = []

    def log(self, message: str) -> None:
        if self.verbose:
            print(f"[INFO] {message}", flush=True)

    def pass_(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("PASS", name, detail))

    def warn(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("WARN", name, detail))

    def fail(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("FAIL", name, detail))

    def require_file(self, path: Path, label: str) -> bool:
        if not path.exists():
            self.fail(label, f"missing file: {path}")
            return False
        if path.is_file() and path.stat().st_size == 0:
            self.fail(label, f"empty file: {path}")
            return False
        self.pass_(label, f"exists: {path}")
        return True

    def load_json(self, path: Path, label: str, required: bool = True) -> Any | None:
        if not path.exists():
            if required:
                self.fail(label, f"missing file: {path}")
            else:
                self.warn(label, f"missing optional file: {path}")
            return None
        self.log(f"Loading JSON: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - validator should report all errors.
            self.fail(label, f"invalid JSON: {exc}")
            return None

    def load_jsonl(self, path: Path, label: str, required: bool = True) -> list[dict[str, Any]]:
        if not path.exists():
            if required:
                self.fail(label, f"missing file: {path}")
            else:
                self.warn(label, f"missing optional file: {path}")
            return []
        rows: list[dict[str, Any]] = []
        size_mb = path.stat().st_size / (1024 * 1024)
        limit_msg = f", max rows={self.max_jsonl_rows}" if self.max_jsonl_rows else ""
        self.log(f"Loading JSONL: {path} ({size_mb:.1f} MB{limit_msg})")
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if self.max_jsonl_rows and len(rows) >= self.max_jsonl_rows:
                        break
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        self.fail(label, f"line {line_no} is not a JSON object")
                        continue
                    row["_line_no"] = line_no
                    rows.append(row)
                    if self.verbose and len(rows) % 1000 == 0:
                        print(f"[INFO]   loaded {len(rows)} rows from {path.name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            self.fail(label, f"invalid JSONL: {exc}")
            return []
        if required and not rows:
            self.fail(label, "zero rows")
        else:
            suffix = "sampled" if self.max_jsonl_rows else "rows"
            self.pass_(label, f"{len(rows)} {suffix}")
        return rows

    def require_columns(
        self,
        rows: list[dict[str, Any]],
        label: str,
        columns: Iterable[str],
        allow_empty: bool = False,
    ) -> bool:
        if not rows:
            if allow_empty:
                self.pass_(label, "empty table allowed")
            else:
                self.fail(label, "no rows to validate")
            return allow_empty
        missing_counts: dict[str, int] = {}
        for row in rows:
            for col in columns:
                if col not in row:
                    missing_counts[col] = missing_counts.get(col, 0) + 1
        if missing_counts:
            self.fail(label, f"missing columns by row count: {missing_counts}")
            return False
        self.pass_(label, f"required columns present ({len(rows)} rows)")
        return True

    def unique_key(self, rows: list[dict[str, Any]], key: str, label: str, allow_empty: bool = False) -> set[str]:
        if not rows:
            if allow_empty:
                self.pass_(label, "empty table allowed")
            else:
                self.fail(label, "no rows")
            return set()
        values = [str(row.get(key, "")) for row in rows]
        blanks = sum(1 for value in values if not value)
        if blanks:
            self.fail(label, f"{blanks} blank {key} values")
            return set(values)
        duplicate_count = len(values) - len(set(values))
        if duplicate_count:
            self.fail(label, f"{duplicate_count} duplicate {key} values")
        else:
            self.pass_(label, f"unique {key}")
        return set(values)

    def parse_time(self, value: Any, label: str) -> pd.Timestamp | None:
        if value in (None, ""):
            self.fail(label, "missing timestamp")
            return None
        try:
            ts = pd.to_datetime(value, utc=True, errors="coerce")
        except Exception as exc:  # noqa: BLE001
            self.fail(label, f"cannot parse timestamp {value!r}: {exc}")
            return None
        if pd.isna(ts):
            self.fail(label, f"unparseable timestamp {value!r}")
            return None
        return ts

    def check_time_range(self, rows: list[dict[str, Any]], time_key: str, label: str) -> None:
        bad = 0
        for row in rows:
            ts = self.parse_time(row.get(time_key), f"{label} {time_key} line {row.get('_line_no')}")
            if ts is None:
                bad += 1
                continue
            if ts < DATASET_START or ts > DATASET_END:
                bad += 1
        if bad:
            self.fail(label, f"{bad} rows have {time_key} outside dataset range")
        else:
            self.pass_(label, f"{time_key} within dataset range")

    def find_leakage_paths(self, value: Any, prefix: str = "$") -> list[str]:
        paths: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                key_str = str(key)
                if key_str.startswith("_"):
                    continue
                if key_str in LEAKAGE_KEYS:
                    paths.append(f"{prefix}.{key_str}")
                paths.extend(self.find_leakage_paths(child, f"{prefix}.{key_str}"))
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                paths.extend(self.find_leakage_paths(child, f"{prefix}[{idx}]"))
        return paths

    def check_no_input_leakage(self) -> None:
        violations: list[str] = []
        for row in self.inputs:
            paths = self.find_leakage_paths(row)
            if paths:
                violations.append(f"{row.get('input_id', 'unknown')}: {paths[:8]}")
        if violations:
            self.fail("materialized_inputs leakage", "; ".join(violations[:5]))
        else:
            self.pass_("materialized_inputs leakage", "no label/reward/future fields found")

    def check_recursive_known_time(self, value: Any, cutoff: pd.Timestamp, label: str) -> tuple[int, int]:
        checked = 0
        violations = 0
        if isinstance(value, dict):
            if "known_time" in value:
                checked += 1
                ts = self.parse_time(value.get("known_time"), f"{label} known_time")
                if ts is None or ts > cutoff:
                    violations += 1
            for key, child in value.items():
                if str(key).startswith("_"):
                    continue
                child_checked, child_violations = self.check_recursive_known_time(child, cutoff, label)
                checked += child_checked
                violations += child_violations
        elif isinstance(value, list):
            for child in value:
                child_checked, child_violations = self.check_recursive_known_time(child, cutoff, label)
                checked += child_checked
                violations += child_violations
        return checked, violations

    def check_materialized_inputs(self) -> None:
        self.log("Phase 1/5: validating materialized inputs")
        base = ADAPT_DIR / "materialized_inputs"
        jsonl_path = base / "inputs.jsonl"
        parquet_path = base / "inputs.parquet"
        manifest_path = base / "manifest.json"

        self.inputs = self.load_jsonl(jsonl_path, "materialized_inputs JSONL", required=True)
        self.require_file(parquet_path, "materialized_inputs parquet")
        self.check_inputs_parquet(parquet_path)
        manifest = self.load_json(manifest_path, "materialized_inputs manifest", required=True)
        if isinstance(manifest, dict):
            self.pass_("materialized_inputs manifest JSON", "valid object")

        required = [
            "input_id",
            "snapshot_id",
            "dataset_version",
            "symbol",
            "instrument_id",
            "analysis_date",
            "analysis_time",
            "known_time_cutoff",
            "input_policy_id",
            "coverage",
            "created_at",
        ]
        if not self.require_columns(self.inputs, "materialized_inputs columns", required):
            return

        self.unique_key(self.inputs, "input_id", "materialized_inputs primary key")
        self.check_time_range(self.inputs, "analysis_time", "materialized_inputs analysis_time")
        self.check_no_input_leakage()

        symbols = {str(row.get("symbol")) for row in self.inputs}
        missing_symbols = sorted(MVP_SYMBOLS - symbols)
        unexpected_symbols = sorted(symbols - MVP_SYMBOLS)
        if missing_symbols:
            self.fail("materialized_inputs symbols", f"missing MVP symbols: {missing_symbols}")
        elif unexpected_symbols:
            self.warn("materialized_inputs symbols", f"unexpected symbols: {unexpected_symbols}")
        else:
            self.pass_("materialized_inputs symbols", sorted(symbols).__repr__())

        mismatch = 0
        recursive_checked = 0
        recursive_violations = 0
        bad_coverage = 0
        for idx, row in enumerate(self.inputs, start=1):
            if self.verbose and idx % 1000 == 0:
                print(f"[INFO]   checked temporal/leakage for {idx} materialized inputs", flush=True)
            analysis_time = self.parse_time(row.get("analysis_time"), f"input {row.get('input_id')} analysis_time")
            cutoff = self.parse_time(row.get("known_time_cutoff"), f"input {row.get('input_id')} known_time_cutoff")
            if analysis_time is None or cutoff is None:
                continue
            if cutoff != analysis_time:
                mismatch += 1
            checked, violations = self.check_recursive_known_time(row, cutoff, f"input {row.get('input_id')}")
            recursive_checked += checked
            recursive_violations += violations
            coverage = row.get("coverage")
            if not isinstance(coverage, dict):
                bad_coverage += 1
            else:
                for value in coverage.values():
                    if str(value) not in ALLOWED_COVERAGE:
                        bad_coverage += 1
                        break

        if mismatch:
            self.fail("materialized_inputs cutoff", f"{mismatch} rows have known_time_cutoff != analysis_time")
        else:
            self.pass_("materialized_inputs cutoff", "known_time_cutoff equals analysis_time")

        if recursive_violations:
            self.fail(
                "materialized_inputs temporal leakage",
                f"{recursive_violations}/{recursive_checked} embedded known_time values exceed cutoff",
            )
        else:
            self.pass_(
                "materialized_inputs temporal leakage",
                f"{recursive_checked} embedded known_time values checked",
            )

        if bad_coverage:
            self.fail("materialized_inputs coverage", f"{bad_coverage} rows have invalid coverage")
        else:
            self.pass_("materialized_inputs coverage", "coverage values valid")

    def check_inputs_parquet(self, parquet_path: Path) -> None:
        self.log(f"Loading Parquet metadata: {parquet_path}")
        try:
            df = pd.read_parquet(parquet_path, engine="pyarrow")
        except Exception as exc:  # noqa: BLE001
            self.fail("materialized_inputs parquet read", f"cannot read parquet: {exc}")
            return
        if df.empty:
            self.fail("materialized_inputs parquet rows", "zero rows")
            return
        self.pass_("materialized_inputs parquet read", f"{len(df)} rows")
        required = {
            "input_id",
            "snapshot_id",
            "symbol",
            "instrument_id",
            "analysis_date",
            "analysis_time",
            "known_time_cutoff",
            "input_policy_id",
        }
        missing = sorted(required - set(df.columns))
        if missing:
            self.fail("materialized_inputs parquet columns", f"missing {missing}")
        else:
            self.pass_("materialized_inputs parquet columns", "required metadata columns present")
        payload_like = {
            "market_window",
            "financial_statement_window",
            "ticker_news_window",
            "macro_news_window",
            "social_window",
            "latest_market_snapshot",
            "technical_snapshot",
            "fundamentals_snapshot",
        }
        present_payload = sorted(payload_like & set(df.columns))
        if present_payload:
            self.fail("materialized_inputs parquet payload", f"payload-heavy columns present: {present_payload}")
        else:
            self.pass_("materialized_inputs parquet payload", "no heavy payload columns")

    def check_episodes(self) -> None:
        self.log("Phase 2/5: validating episodes")
        base = ADAPT_DIR / "episodes"
        self.episodes = self.load_jsonl(base / "trading_episodes.jsonl", "episodes JSONL", required=True)
        manifest = self.load_json(base / "manifest.json", "episodes manifest", required=True)
        if isinstance(manifest, dict):
            self.pass_("episodes manifest JSON", "valid object")

        required = [
            "episode_id",
            "symbol",
            "instrument_id",
            "analysis_date",
            "analysis_time",
            "known_time_cutoff",
            "input_id",
            "target_workflow",
            "target_agents",
            "label_refs",
            "coverage",
            "episode_version",
            "created_at",
        ]
        if not self.require_columns(self.episodes, "episodes columns", required):
            return

        episode_ids = self.unique_key(self.episodes, "episode_id", "episodes primary key")
        _ = episode_ids
        input_ids = {str(row.get("input_id")) for row in self.inputs}
        missing_inputs = sorted({str(row.get("input_id")) for row in self.episodes} - input_ids)
        if missing_inputs:
            self.fail("episodes input refs", f"{len(missing_inputs)} episode input_id values not found")
        else:
            self.pass_("episodes input refs", "all input_id values exist")

        symbols = {str(row.get("symbol")) for row in self.episodes}
        missing_symbols = sorted(MVP_SYMBOLS - symbols)
        if missing_symbols:
            self.fail("episodes symbols", f"missing MVP symbols: {missing_symbols}")
        else:
            self.pass_("episodes symbols", sorted(symbols).__repr__())

        bad_label_refs = 0
        leaked_label_values = 0
        bad_agents = 0
        for row in self.episodes:
            label_refs = row.get("label_refs")
            if not isinstance(label_refs, dict) or set(label_refs) != HORIZONS:
                bad_label_refs += 1
            else:
                for value in label_refs.values():
                    if not isinstance(value, str) or not value.startswith("trading_labels?"):
                        bad_label_refs += 1
                        break
            target_agents = row.get("target_agents")
            if not isinstance(target_agents, list) or not target_agents:
                bad_agents += 1
            if self.find_leakage_paths({k: v for k, v in row.items() if k != "label_refs"}):
                leaked_label_values += 1

        if bad_label_refs:
            self.fail("episodes label_refs", f"{bad_label_refs} rows have invalid label_refs")
        else:
            self.pass_("episodes label_refs", "all horizons present as refs")

        if leaked_label_values:
            self.fail("episodes leakage", f"{leaked_label_values} rows contain label/reward values outside label_refs")
        else:
            self.pass_("episodes leakage", "no embedded label/reward values outside refs")

        if bad_agents:
            self.fail("episodes target_agents", f"{bad_agents} rows have invalid target_agents")
        else:
            self.pass_("episodes target_agents", "valid non-empty target_agents")

        self.check_time_range(self.episodes, "analysis_time", "episodes analysis_time")

    def check_policy_file(
        self,
        path: Path,
        label: str,
        id_key: str,
        required_ids: set[str],
        required_columns: Iterable[str],
    ) -> list[dict[str, Any]]:
        payload = self.load_json(path, label, required=True)
        if not isinstance(payload, list):
            self.fail(label, "expected a JSON array")
            return []
        rows = [row for row in payload if isinstance(row, dict)]
        if len(rows) != len(payload):
            self.fail(label, "all items must be JSON objects")
            return rows
        self.pass_(label, f"{len(rows)} policies")
        self.require_columns(rows, f"{label} columns", required_columns)
        ids = self.unique_key(rows, id_key, f"{label} primary key")
        missing = sorted(required_ids - ids)
        if missing:
            self.fail(label, f"missing required IDs: {missing}")
        else:
            self.pass_(label, "required IDs present")
        return rows

    def check_policies(self) -> None:
        self.log("Phase 3/5: validating context/memory/prompt policies")
        self.context_policies = self.check_policy_file(
            ADAPT_DIR / "context_policies" / "context_policies.json",
            "context_policies",
            "context_policy_id",
            {"ctx_default_v1", "ctx_short_market_v1", "ctx_long_market_v1"},
            [
                "context_policy_id",
                "description",
                "market_window_days",
                "technical_indicators",
                "fundamentals_quarters",
                "max_ticker_news",
                "max_macro_news",
                "max_social_items",
            ],
        )
        self.memory_policies = self.check_policy_file(
            ADAPT_DIR / "memory_policies" / "memory_policies.json",
            "memory_policies",
            "memory_policy_id",
            {"mem_none_v1", "mem_top5_role_v1", "mem_top3_regime_v1"},
            [
                "memory_policy_id",
                "description",
                "top_k_memories",
                "same_symbol_boost",
                "same_regime_required",
                "agent_role_filter",
            ],
        )
        self.prompt_variants = self.check_policy_file(
            ADAPT_DIR / "prompt_variants" / "prompt_variants.json",
            "prompt_variants",
            "prompt_variant_id",
            {
                "prompt_default_v1",
                "prompt_evidence_based_v1",
                "prompt_risk_aware_v1",
                "prompt_memory_aware_v1",
            },
            [
                "prompt_variant_id",
                "agent_role",
                "base_prompt_id",
                "variant_type",
                "instruction_patch",
            ],
        )

        bad_context = 0
        for row in self.context_policies:
            if int(row.get("market_window_days", 0)) <= 0:
                bad_context += 1
            if not isinstance(row.get("technical_indicators"), list) or not row.get("technical_indicators"):
                bad_context += 1
        if bad_context:
            self.fail("context_policies values", f"{bad_context} invalid policies")
        else:
            self.pass_("context_policies values", "valid positive windows and indicators")

        bad_memory = 0
        for row in self.memory_policies:
            if int(row.get("top_k_memories", -1)) < 0:
                bad_memory += 1
        if bad_memory:
            self.fail("memory_policies values", f"{bad_memory} invalid policies")
        else:
            self.pass_("memory_policies values", "valid top_k_memories")

    def check_adaptation_runs(self) -> None:
        self.log("Phase 4/5: validating adaptation runs")
        base = ADAPT_DIR / "adaptation_runs"
        self.adaptation_runs = self.load_jsonl(base / "adaptation_runs.jsonl", "adaptation_runs JSONL", required=True)
        manifest = self.load_json(base / "manifest.json", "adaptation_runs manifest", required=True)
        if isinstance(manifest, dict):
            self.pass_("adaptation_runs manifest JSON", "valid object")

        required = [
            "adaptation_run_id",
            "episode_id",
            "input_id",
            "context_policy_id",
            "memory_policy_id",
            "prompt_variant_ids",
            "target_workflow",
            "status",
            "created_at",
        ]
        if not self.require_columns(self.adaptation_runs, "adaptation_runs columns", required):
            return

        self.unique_key(self.adaptation_runs, "adaptation_run_id", "adaptation_runs primary key")
        episode_ids = {str(row.get("episode_id")) for row in self.episodes}
        input_ids = {str(row.get("input_id")) for row in self.inputs}
        context_ids = {str(row.get("context_policy_id")) for row in self.context_policies}
        memory_ids = {str(row.get("memory_policy_id")) for row in self.memory_policies}
        prompt_ids = {str(row.get("prompt_variant_id")) for row in self.prompt_variants}

        bad_refs = 0
        bad_status = 0
        bad_prompt = 0
        for row in self.adaptation_runs:
            if str(row.get("episode_id")) not in episode_ids:
                bad_refs += 1
            if str(row.get("input_id")) not in input_ids:
                bad_refs += 1
            if str(row.get("context_policy_id")) not in context_ids:
                bad_refs += 1
            if str(row.get("memory_policy_id")) not in memory_ids:
                bad_refs += 1
            if str(row.get("status")) not in ALLOWED_RUN_STATUS:
                bad_status += 1
            variants = row.get("prompt_variant_ids")
            if not isinstance(variants, list) or not variants or any(str(v) not in prompt_ids for v in variants):
                bad_prompt += 1

        if bad_refs:
            self.fail("adaptation_runs refs", f"{bad_refs} invalid references")
        else:
            self.pass_("adaptation_runs refs", "all episode/input/context/memory refs valid")

        if bad_status:
            self.fail("adaptation_runs status", f"{bad_status} invalid statuses")
        else:
            self.pass_("adaptation_runs status", "valid statuses")

        if bad_prompt:
            self.fail("adaptation_runs prompt refs", f"{bad_prompt} invalid prompt_variant_ids")
        else:
            self.pass_("adaptation_runs prompt refs", "valid prompt_variant_ids")

        episode_count = max(1, len(episode_ids))
        runs_per_episode = len(self.adaptation_runs) / episode_count
        if runs_per_episode > 20:
            self.warn("adaptation_runs size", f"{runs_per_episode:.1f} runs/episode; check cost control")
        else:
            self.pass_("adaptation_runs size", f"{runs_per_episode:.1f} runs/episode")

    def check_label_refs_against_labels(self) -> None:
        self.log("Phase 5/5: validating episode label refs against trading_labels")
        labels_path = DATA_DIR / "features" / "trading_labels"
        if not labels_path.exists():
            self.fail("trading_labels lookup", f"missing {labels_path}")
            return
        try:
            labels = pd.read_parquet(labels_path, engine="pyarrow")
        except Exception as exc:  # noqa: BLE001
            self.fail("trading_labels lookup", f"cannot read labels: {exc}")
            return
        required = {"instrument_id", "analysis_date", "horizon_days"}
        missing = required - set(labels.columns)
        if missing:
            self.fail("trading_labels lookup", f"missing columns: {sorted(missing)}")
            return
        keys = {
            (
                str(row.instrument_id),
                str(row.analysis_date)[:10],
                str(row.horizon_days).replace("d", ""),
            )
            for row in labels[["instrument_id", "analysis_date", "horizon_days"]].itertuples(index=False)
        }
        missing_refs = 0
        for episode in self.episodes:
            for horizon in HORIZONS:
                key = (
                    str(episode.get("instrument_id")),
                    str(episode.get("analysis_date"))[:10],
                    horizon.replace("d", ""),
                )
                if key not in keys:
                    missing_refs += 1
        if missing_refs:
            self.fail("episodes labels lookup", f"{missing_refs} episode horizon refs not found in trading_labels")
        else:
            self.pass_("episodes labels lookup", "all episode horizons found in trading_labels")

    def run(self) -> int:
        self.check_materialized_inputs()
        self.check_episodes()
        self.check_policies()
        self.check_adaptation_runs()
        self.check_label_refs_against_labels()
        return self.report()

    def report(self) -> int:
        print("\nMeMo adaptation dataset validation report")
        print("=" * 45)
        for result in self.results:
            detail = f" - {result.detail}" if result.detail else ""
            print(f"[{result.level}] {result.name}{detail}")
        pass_count = sum(1 for result in self.results if result.level == "PASS")
        warn_count = sum(1 for result in self.results if result.level == "WARN")
        fail_count = sum(1 for result in self.results if result.level == "FAIL")
        print("=" * 45)
        print(f"PASS={pass_count} WARN={warn_count} FAIL={fail_count}")
        return 1 if fail_count else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate phase-1 MemoAdapt MeMo adaptation input/run-plan dataset."
    )
    parser.add_argument(
        "--max-jsonl-rows",
        type=int,
        default=0,
        help="Validate only the first N rows of large JSONL files. Default 0 means all rows.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable progress logs and print only the final validation report.",
    )
    args = parser.parse_args(argv)
    validator = Validator(max_jsonl_rows=args.max_jsonl_rows, verbose=not args.quiet)
    return validator.run()


if __name__ == "__main__":
    raise SystemExit(main())
