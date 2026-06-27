"""Preflight validation for the MeMo tournament before any paid/API run.

This validator is intentionally different from validate_memo_tournament_dataset.py:

- It does not require API keys.
- It does not require real trajectories/rewards/scores/champions.
- It verifies that the seed/config/runner dry-run flow is stable.
- It fails if mock "succeeded" trajectories are mixed into the real output path.

Usage:
    python DataLake/tools/validation/validate_memo_tournament_preflight.py
    python DataLake/tools/validation/validate_memo_tournament_preflight.py --require-dry-run-output
    python DataLake/tools/validation/validate_memo_tournament_preflight.py --allow-mock-artifacts
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DATALAKE_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = DATALAKE_DIR.parent
DATA_DIR = DATALAKE_DIR / "data" / "memo_adaptation"

TRAINING_START = pd.Timestamp("2022-01-03T00:00:00Z")
TRAINING_END = pd.Timestamp("2022-12-30T23:59:59Z")
MVP_SYMBOLS = {"AAPL", "AMZN", "GOOGL"}
SEED_PROMPT_SET_IDS = {
    "ps_default_v1",
    "ps_risk_aware_v1",
    "ps_macro_defensive_v1",
}
GEN0_ID = "gen_2022_00"
TOUR_GEN0_ID = "tour_2022_gen0"

API_ENV_KEYS = {
    "OPENAI_API_KEY",
    "OPENAI_COMPATIBLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "FINNHUB_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
}


@dataclass
class CheckResult:
    level: str
    name: str
    detail: str = ""


class PreflightValidator:
    def __init__(
        self,
        require_dry_run_output: bool = False,
        allow_mock_artifacts: bool = False,
        verbose: bool = True,
    ):
        self.require_dry_run_output = require_dry_run_output
        self.allow_mock_artifacts = allow_mock_artifacts
        self.verbose = verbose
        self.results: list[CheckResult] = []
        self.episodes: list[dict[str, Any]] = []
        self.prompt_sets: list[dict[str, Any]] = []
        self.generations: list[dict[str, Any]] = []
        self.tournaments: list[dict[str, Any]] = []

    def log(self, message: str) -> None:
        if self.verbose:
            print(f"[INFO] {message}", flush=True)

    def pass_(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("PASS", name, detail))

    def warn(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("WARN", name, detail))

    def fail(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("FAIL", name, detail))

    def load_json(self, path: Path, label: str, required: bool = True) -> Any | None:
        if not path.exists():
            if required:
                self.fail(label, f"missing file: {path}")
            else:
                self.warn(label, f"missing optional file: {path}")
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
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
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        self.fail(label, f"line {line_no} is not a JSON object")
                        continue
                    row["_line_no"] = line_no
                    rows.append(row)
        except Exception as exc:  # noqa: BLE001
            self.fail(label, f"invalid JSONL: {exc}")
            return []
        if required and not rows:
            self.fail(label, "zero rows")
        else:
            self.pass_(label, f"{len(rows)} rows")
        return rows

    def parse_time(self, value: Any, label: str) -> pd.Timestamp | None:
        try:
            ts = pd.to_datetime(value, utc=True, errors="coerce")
        except Exception as exc:  # noqa: BLE001
            self.fail(label, f"cannot parse {value!r}: {exc}")
            return None
        if pd.isna(ts):
            self.fail(label, f"unparseable timestamp {value!r}")
            return None
        return ts

    def check_base_dataset(self) -> None:
        self.log("Checking base memo_adaptation dataset")
        self.episodes = self.load_jsonl(
            DATA_DIR / "episodes" / "trading_episodes.jsonl",
            "base episodes",
            required=True,
        )
        inputs_parquet = DATA_DIR / "materialized_inputs" / "inputs.parquet"
        if not inputs_parquet.exists():
            self.fail("base materialized_inputs parquet", f"missing {inputs_parquet}")
        else:
            try:
                df = pd.read_parquet(inputs_parquet)
                required = {"input_id", "symbol", "analysis_time"}
                missing = sorted(required - set(df.columns))
                if missing:
                    self.fail("base materialized_inputs parquet", f"missing columns {missing}")
                else:
                    self.pass_("base materialized_inputs parquet", f"{len(df)} metadata rows")
            except Exception as exc:  # noqa: BLE001
                self.fail("base materialized_inputs parquet", f"cannot read: {exc}")

        episodes_2022 = []
        bad_episode_time = 0
        bad_symbols = 0
        for row in self.episodes:
            symbol = str(row.get("symbol"))
            ts = self.parse_time(row.get("analysis_time"), f"episode {row.get('episode_id')} analysis_time")
            if symbol not in MVP_SYMBOLS:
                bad_symbols += 1
            if ts is None:
                bad_episode_time += 1
                continue
            if TRAINING_START <= ts <= TRAINING_END and symbol in MVP_SYMBOLS:
                episodes_2022.append(row)
        if bad_episode_time:
            self.fail("base episodes temporal parse", f"{bad_episode_time} invalid rows")
        else:
            self.pass_("base episodes temporal parse", "all analysis_time values parse")
        if bad_symbols:
            self.warn("base episodes symbols", f"{bad_symbols} rows outside MVP symbols")
        else:
            self.pass_("base episodes symbols", "only MVP symbols")
        if len(episodes_2022) < 700:
            self.fail("base episodes 2022 coverage", f"only {len(episodes_2022)} AAPL/AMZN/GOOGL episodes")
        else:
            self.pass_("base episodes 2022 coverage", f"{len(episodes_2022)} AAPL/AMZN/GOOGL episodes")

    def check_seed_contract(self) -> None:
        self.log("Checking Gen0 prompt/tournament seed contract")
        self.prompt_sets = self.load_jsonl(DATA_DIR / "prompt_sets" / "prompt_sets.jsonl", "prompt_sets")
        self.generations = self.load_jsonl(
            DATA_DIR / "prompt_generations" / "prompt_generations.jsonl",
            "prompt_generations",
        )
        self.tournaments = self.load_jsonl(DATA_DIR / "tournaments" / "tournaments.jsonl", "tournaments")

        prompt_ids = {str(row.get("prompt_set_id")) for row in self.prompt_sets}
        missing = sorted(SEED_PROMPT_SET_IDS - prompt_ids)
        if missing:
            self.fail("Gen0 seed prompt IDs", f"missing {missing}")
        else:
            self.pass_("Gen0 seed prompt IDs", "all 3 seed prompt sets present")

        bad_prompt_rows = 0
        for row in self.prompt_sets:
            if str(row.get("prompt_set_id")) in SEED_PROMPT_SET_IDS:
                patches = row.get("role_patches")
                if not isinstance(patches, dict) or not patches:
                    bad_prompt_rows += 1
                if row.get("created_from") != "seed":
                    bad_prompt_rows += 1
                if int(row.get("generation", -1)) != 0:
                    bad_prompt_rows += 1
        if bad_prompt_rows:
            self.fail("Gen0 seed prompt values", f"{bad_prompt_rows} invalid rows")
        else:
            self.pass_("Gen0 seed prompt values", "patches/created_from/generation valid")

        gen0 = next((row for row in self.generations if row.get("generation_id") == GEN0_ID), None)
        if not gen0:
            self.fail("Gen0 generation", f"missing {GEN0_ID}")
        else:
            ids = set(map(str, gen0.get("prompt_set_ids", [])))
            if ids != SEED_PROMPT_SET_IDS or int(gen0.get("population_size", -1)) != 3:
                self.fail("Gen0 generation", "population_size or prompt_set_ids mismatch")
            else:
                self.pass_("Gen0 generation", "population size 3 and prompt refs valid")

        tour0 = next((row for row in self.tournaments if row.get("tournament_id") == TOUR_GEN0_ID), None)
        if not tour0:
            self.fail("Gen0 tournament", f"missing {TOUR_GEN0_ID}")
        else:
            episode_filter = tour0.get("episode_filter", {})
            symbols = set(episode_filter.get("symbols", [])) if isinstance(episode_filter, dict) else set()
            if tour0.get("generation_id") != GEN0_ID or symbols != MVP_SYMBOLS:
                self.fail("Gen0 tournament", "generation_id or symbol filter mismatch")
            elif tour0.get("status") != "planned":
                self.fail("Gen0 tournament", "preflight tournament status must remain planned")
            else:
                self.pass_("Gen0 tournament", "planned 2022 AAPL/AMZN/GOOGL tournament")

    def check_runner_contract(self) -> None:
        self.log("Checking runner no-API dry-run contract")
        runner_path = DATALAKE_DIR / "run_memo_tournament.py"
        adapter_path = DATALAKE_DIR / "adapters" / "tradingagents_prompt_patch.py"
        if not runner_path.exists():
            self.fail("runner file", f"missing {runner_path}")
            return
        if not adapter_path.exists():
            self.fail("prompt patch adapter", f"missing {adapter_path}")
        else:
            self.pass_("prompt patch adapter", "file exists")

        source = runner_path.read_text(encoding="utf-8")
        required_fragments = [
            "--dry-run",
            "api_required",
            "writes_trajectories",
            "Dry-run mode enabled",
            "no LLM/API calls",
            "no trajectories were written",
        ]
        missing = [fragment for fragment in required_fragments if fragment not in source]
        if missing:
            self.fail("runner dry-run support", f"missing source fragments {missing}")
        else:
            self.pass_("runner dry-run support", "has explicit no-API dry-run path")

        dry_pos = source.find("if args.dry_run")
        real_pos = source.find("final_state = run_real_tradingagents(")
        if dry_pos < 0 or real_pos < 0:
            self.fail("runner dry-run ordering", "cannot locate dry-run block or real runner call")
        elif dry_pos > real_pos:
            self.fail("runner dry-run ordering", "dry-run block appears after real runner call")
        else:
            self.pass_("runner dry-run ordering", "dry-run exits before real TradingAgents execution")

        present_api_keys = sorted(key for key in API_ENV_KEYS if os.getenv(key))
        if present_api_keys:
            self.warn("API env keys", f"present but not required for preflight: {present_api_keys}")
        else:
            self.pass_("API env keys", "none present and none required for preflight")

    def check_dry_run_output(self) -> None:
        self.log("Checking dry-run output contract")
        latest = self.load_json(DATA_DIR / "dry_runs" / "latest_dry_run.json", "latest dry-run output", required=True)
        if not isinstance(latest, dict):
            return
        if latest.get("mode") != "dry_run_no_api":
            self.fail("dry-run mode", f"unexpected mode {latest.get('mode')!r}")
        else:
            self.pass_("dry-run mode", "dry_run_no_api")
        if latest.get("api_required") is not False:
            self.fail("dry-run api_required", "must be false")
        else:
            self.pass_("dry-run api_required", "false")
        if latest.get("writes_trajectories") is not False:
            self.fail("dry-run writes_trajectories", "must be false")
        else:
            self.pass_("dry-run writes_trajectories", "false")
        if latest.get("tournament_id") != TOUR_GEN0_ID or latest.get("generation_id") != GEN0_ID:
            self.fail("dry-run refs", "unexpected tournament_id/generation_id")
        else:
            self.pass_("dry-run refs", "Gen0 tournament/generation")
        if set(latest.get("symbols", [])) != MVP_SYMBOLS:
            self.fail("dry-run symbols", f"unexpected symbols {latest.get('symbols')}")
        else:
            self.pass_("dry-run symbols", "AAPL/AMZN/GOOGL")
        if set(latest.get("prompt_set_ids", [])) != SEED_PROMPT_SET_IDS:
            self.fail("dry-run prompt sets", f"unexpected prompt_set_ids {latest.get('prompt_set_ids')}")
        else:
            self.pass_("dry-run prompt sets", "3 Gen0 prompt sets")
        for field in ["selected_episode_count", "planned_run_count", "executable_run_count_after_resume", "limited_run_count"]:
            try:
                value = int(latest.get(field))
                if value < 0:
                    raise ValueError("negative")
            except Exception:
                self.fail(f"dry-run {field}", f"invalid value {latest.get(field)!r}")
            else:
                self.pass_(f"dry-run {field}", str(value))

    def check_no_mock_pollution(self) -> None:
        self.log("Checking that mock runs are not mixed into real trajectory output")
        trajectories_path = DATA_DIR / "trajectories" / "workflow_trajectories.jsonl"
        if not trajectories_path.exists():
            self.pass_("mock artifact pollution", "no trajectory file yet")
            return
        rows = self.load_jsonl(trajectories_path, "existing trajectories", required=False)
        mock_succeeded = []
        for row in rows:
            outputs = row.get("agent_outputs", {})
            output_text = json.dumps(outputs, ensure_ascii=False).lower() if isinstance(outputs, dict) else ""
            if row.get("run_status") == "succeeded" and "mock" in output_text:
                mock_succeeded.append(str(row.get("trajectory_id")))
        if mock_succeeded and not self.allow_mock_artifacts:
            self.fail(
                "mock artifact pollution",
                f"{len(mock_succeeded)} mock succeeded trajectories found; remove/archive before real API test. sample={mock_succeeded[:5]}",
            )
        elif mock_succeeded:
            self.warn("mock artifact pollution", f"allowed by flag: {len(mock_succeeded)} mock succeeded trajectories")
        else:
            self.pass_("mock artifact pollution", "no mock succeeded trajectories in real output path")

    def run(self) -> int:
        self.check_base_dataset()
        self.check_seed_contract()
        self.check_runner_contract()
        if self.require_dry_run_output:
            self.check_dry_run_output()
        else:
            self.warn("dry-run output", "not required; run with --require-dry-run-output after dry-run command")
        self.check_no_mock_pollution()
        return self.report()

    def report(self) -> int:
        print("\nMeMo tournament preflight validation report")
        print("=" * 48)
        for result in self.results:
            detail = f" - {result.detail}" if result.detail else ""
            print(f"[{result.level}] {result.name}{detail}")
        pass_count = sum(1 for result in self.results if result.level == "PASS")
        warn_count = sum(1 for result in self.results if result.level == "WARN")
        fail_count = sum(1 for result in self.results if result.level == "FAIL")
        print("=" * 48)
        print(f"PASS={pass_count} WARN={warn_count} FAIL={fail_count}")
        return 1 if fail_count else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate no-API MeMo tournament preflight flow.")
    parser.add_argument(
        "--require-dry-run-output",
        action="store_true",
        help="Require DataLake/data/memo_adaptation/dry_runs/latest_dry_run.json.",
    )
    parser.add_argument(
        "--allow-mock-artifacts",
        action="store_true",
        help="Warn instead of failing if mock succeeded trajectories exist.",
    )
    parser.add_argument("--quiet", action="store_true", help="Disable progress logs.")
    args = parser.parse_args(argv)
    validator = PreflightValidator(
        require_dry_run_output=args.require_dry_run_output,
        allow_mock_artifacts=args.allow_mock_artifacts,
        verbose=not args.quiet,
    )
    return validator.run()


if __name__ == "__main__":
    raise SystemExit(main())
