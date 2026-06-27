"""Validate the DataLake outputs after crawler/builder runs.

Usage:
    python DataLake/tools/validation/validate_dataset.py
    python DataLake/tools/validation/validate_dataset.py --strict-optional

The validator is intentionally standalone: it uses only pandas/pyarrow/json from
the existing project dependencies and does not require pytest. Core datasets
must pass. Optional datasets emit warnings by default because historical
news/social/API coverage can legitimately be partial.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


DATALAKE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = DATALAKE_DIR / "data"
MANIFEST_PATH = DATALAKE_DIR / "manifests" / "dataset_manifest.json"

MVP_SYMBOLS = {"AAPL", "AMZN", "GOOGL"}
BENCHMARKS = {"SPY", "QQQ"}
ALL_MARKET_SYMBOLS = MVP_SYMBOLS | BENCHMARKS
DATASET_START = pd.Timestamp("2019-01-01", tz="UTC")
DATASET_END = pd.Timestamp("2023-12-31 23:59:59", tz="UTC")
WARMUP_START = pd.Timestamp("2018-01-01", tz="UTC")


@dataclass
class CheckResult:
    level: str
    name: str
    detail: str


class Validator:
    def __init__(self, strict_optional: bool = False):
        self.strict_optional = strict_optional
        self.results: list[CheckResult] = []
        self.cache: dict[tuple[str, str], pd.DataFrame] = {}

    def pass_(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("PASS", name, detail))

    def warn(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("WARN", name, detail))

    def fail(self, name: str, detail: str = "") -> None:
        self.results.append(CheckResult("FAIL", name, detail))

    def path_for(self, layer: str, dataset: str) -> Path:
        return DATA_DIR / layer / dataset

    def load_parquet_dataset(self, layer: str, dataset: str) -> pd.DataFrame | None:
        key = (layer, dataset)
        if key in self.cache:
            return self.cache[key]

        path = self.path_for(layer, dataset)
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path, engine="pyarrow")
        except Exception as exc:  # noqa: BLE001 - validator should report all errors.
            self.fail(f"load {layer}/{dataset}", str(exc))
            return None
        self.cache[key] = df
        return df

    def require_columns(
        self,
        df: pd.DataFrame | None,
        label: str,
        columns: Iterable[str],
        optional: bool = False,
    ) -> bool:
        if df is None:
            msg = "dataset missing"
            if optional and not self.strict_optional:
                self.warn(label, msg)
            else:
                self.fail(label, msg)
            return False
        missing = [c for c in columns if c not in df.columns]
        if missing:
            self.fail(label, f"missing columns: {missing}")
            return False
        self.pass_(label, f"columns ok ({len(df)} rows)")
        return True

    def parse_time_col(self, df: pd.DataFrame, col: str, label: str) -> pd.Series | None:
        try:
            values = pd.to_datetime(df[col], utc=True, errors="coerce")
        except Exception as exc:  # noqa: BLE001
            self.fail(label, f"cannot parse {col}: {exc}")
            return None
        null_count = int(values.isna().sum())
        if null_count:
            self.fail(label, f"{col} has {null_count} unparsable/null values")
            return None
        return values

    def check_temporal_contract(
        self,
        df: pd.DataFrame | None,
        label: str,
        optional: bool = False,
        allow_known_after_scope: bool = False,
    ) -> bool:
        if not self.require_columns(df, f"{label} temporal columns", ["event_time", "known_time"], optional):
            return False
        assert df is not None
        event_time = self.parse_time_col(df, "event_time", label)
        known_time = self.parse_time_col(df, "known_time", label)
        if event_time is None or known_time is None:
            return False
        if (known_time < event_time).any():
            count = int((known_time < event_time).sum())
            self.warn(label, f"{count} rows have known_time before event_time; verify source semantics")
        if not allow_known_after_scope and (known_time > DATASET_END).any():
            count = int((known_time > DATASET_END).sum())
            self.fail(label, f"{count} rows have known_time after dataset scope")
            return False
        self.pass_(label, "temporal contract ok")
        return True

    def check_manifest(self) -> None:
        if not MANIFEST_PATH.exists():
            self.fail("manifest", f"missing {MANIFEST_PATH}")
            return
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self.fail("manifest", f"invalid JSON: {exc}")
            return
        scope = manifest.get("scope", {})
        symbols = set(scope.get("ticker_universe_mvp", []))
        benchmarks = set(scope.get("benchmarks", []))
        if not MVP_SYMBOLS.issubset(symbols):
            self.fail("manifest symbols", f"expected {sorted(MVP_SYMBOLS)}, got {sorted(symbols)}")
        else:
            self.pass_("manifest symbols", sorted(symbols).__repr__())
        if not BENCHMARKS.issubset(benchmarks):
            self.fail("manifest benchmarks", f"expected {sorted(BENCHMARKS)}, got {sorted(benchmarks)}")
        else:
            self.pass_("manifest benchmarks", sorted(benchmarks).__repr__())

    def check_calendar(self) -> None:
        df = self.load_parquet_dataset("normalized", "trading_calendar")
        if not self.require_columns(
            df,
            "trading_calendar",
            ["calendar_id", "date", "is_trading_day", "market_open", "market_close", "timezone", "source"],
        ):
            return
        assert df is not None
        dates = pd.to_datetime(df["date"], errors="coerce")
        if dates.isna().any():
            self.fail("trading_calendar dates", "date column contains invalid dates")
            return
        in_output = df[(dates >= DATASET_START.tz_localize(None)) & (dates <= DATASET_END.tz_localize(None))]
        if len(in_output) < 1000:
            self.fail("trading_calendar coverage", f"too few trading days in output range: {len(in_output)}")
        else:
            self.pass_("trading_calendar coverage", f"{len(in_output)} rows in output range")

    def check_instrument_master(self) -> None:
        df = self.load_parquet_dataset("normalized", "instrument_master")
        cols = [
            "instrument_id",
            "symbol_yahoo",
            "asset_type",
            "name",
            "exchange",
            "currency",
            "benchmark_symbol",
            "source",
            "event_time",
            "known_time",
        ]
        if not self.require_columns(df, "instrument_master", cols):
            return
        assert df is not None
        ids = set(df["instrument_id"].astype(str))
        missing = sorted(ALL_MARKET_SYMBOLS - ids)
        if missing:
            self.fail("instrument_master symbols", f"missing {missing}")
        else:
            self.pass_("instrument_master symbols", sorted(ids).__repr__())
        if df["instrument_id"].duplicated().any():
            self.fail("instrument_master primary key", "duplicate instrument_id values")
        else:
            self.pass_("instrument_master primary key", "unique instrument_id")
        self.check_temporal_contract(df, "instrument_master", allow_known_after_scope=True)

    def check_price_daily(self) -> None:
        df = self.load_parquet_dataset("normalized", "price_daily")
        cols = [
            "instrument_id",
            "trade_date",
            "event_time",
            "known_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        ]
        if not self.require_columns(df, "price_daily", cols):
            return
        assert df is not None
        self.check_temporal_contract(df, "price_daily")
        ids = set(df["instrument_id"].astype(str))
        missing = sorted(ALL_MARKET_SYMBOLS - ids)
        if missing:
            self.fail("price_daily symbols", f"missing {missing}")
        else:
            self.pass_("price_daily symbols", sorted(ids).__repr__())
        key_cols = ["instrument_id", "trade_date", "source"]
        dupes = int(df.duplicated(key_cols).sum())
        if dupes:
            self.fail("price_daily primary key", f"{dupes} duplicate rows for {key_cols}")
        else:
            self.pass_("price_daily primary key", "no duplicate instrument/date/source")
        for symbol in sorted(ALL_MARKET_SYMBOLS):
            rows = int((df["instrument_id"].astype(str) == symbol).sum())
            if rows < 1200:
                self.fail(f"price_daily coverage {symbol}", f"too few rows: {rows}")
            else:
                self.pass_(f"price_daily coverage {symbol}", f"{rows} rows")
        numeric_cols = ["open", "high", "low", "close", "volume"]
        bad_numeric = df[numeric_cols].isna().sum().sum()
        if bad_numeric:
            self.fail("price_daily null numeric", f"{int(bad_numeric)} null OHLCV values")
        else:
            self.pass_("price_daily null numeric", "none")

    def check_technical_indicators(self) -> None:
        df = self.load_parquet_dataset("features", "technical_indicators_daily")
        cols = [
            "instrument_id",
            "trade_date",
            "event_time",
            "known_time",
            "close_10_ema",
            "close_50_sma",
            "close_200_sma",
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_hist",
            "boll_mid",
            "boll_upper",
            "boll_lower",
            "atr_14",
        ]
        if not self.require_columns(df, "technical_indicators_daily", cols):
            return
        assert df is not None
        self.check_temporal_contract(df, "technical_indicators_daily")
        ids = set(df["instrument_id"].astype(str))
        missing = sorted(ALL_MARKET_SYMBOLS - ids)
        if missing:
            self.fail("technical symbols", f"missing {missing}")
        else:
            self.pass_("technical symbols", sorted(ids).__repr__())
        # Warmup rows can be null for long indicators. After 250 rows per symbol,
        # required indicators should mostly be populated.
        for symbol in sorted(ALL_MARKET_SYMBOLS):
            group = df[df["instrument_id"].astype(str) == symbol].sort_values("trade_date")
            mature = group.iloc[250:] if len(group) > 250 else group.iloc[0:0]
            if mature.empty:
                self.fail(f"technical coverage {symbol}", "not enough rows after warmup")
                continue
            nulls = mature[["close_200_sma", "rsi_14", "macd", "atr_14"]].isna().sum().sum()
            if nulls:
                self.fail(f"technical nulls {symbol}", f"{int(nulls)} null mature indicator values")
            else:
                self.pass_(f"technical nulls {symbol}", "mature indicators populated")

    def check_optional_tables(self) -> None:
        optional_specs = [
            ("normalized", "fundamentals_profile_snapshot", ["instrument_id", "event_time", "known_time", "source"]),
            ("normalized", "financial_statement_line_items", ["instrument_id", "event_time", "known_time", "source"]),
            ("normalized", "earnings_events", ["instrument_id", "event_time", "known_time", "source"]),
            ("normalized", "news_articles", ["article_id", "event_time", "known_time", "query_used", "coverage_status"]),
            ("normalized", "macro_news_articles", ["article_id", "event_time", "known_time", "query_used"]),
            ("normalized", "stocktwits_messages", ["instrument_id", "event_time", "known_time"]),
            ("normalized", "reddit_posts", ["instrument_id", "event_time", "known_time"]),
            ("normalized", "macro_series_observations", ["series_id", "event_time", "known_time"]),
            ("features", "social_sentiment_daily", ["instrument_id", "event_time", "known_time"]),
        ]
        for layer, dataset, cols in optional_specs:
            df = self.load_parquet_dataset(layer, dataset)
            label = f"{layer}/{dataset}"
            if df is None:
                if self.strict_optional:
                    self.fail(label, "optional dataset missing under --strict-optional")
                else:
                    self.warn(label, "optional dataset missing")
                continue
            if not self.require_columns(df, label, cols, optional=True):
                continue
            allow_after = dataset == "fundamentals_profile_snapshot"
            self.check_temporal_contract(df, label, optional=True, allow_known_after_scope=allow_after)
            if dataset in {"news_articles", "macro_news_articles"}:
                self.check_news_like_table(df, label)

    def check_news_like_table(self, df: pd.DataFrame, label: str) -> None:
        if df.empty:
            self.warn(label, "table exists but has zero rows")
            return
        if "vendor" in df.columns:
            vendors = sorted(set(df["vendor"].dropna().astype(str)))
            self.pass_(f"{label} vendors", ", ".join(vendors) or "<none>")
        if "query_used" in df.columns and df["query_used"].isna().all():
            self.fail(f"{label} query_used", "all query_used values are null")
        if "relevance_score" in df.columns:
            scores = pd.to_numeric(df["relevance_score"], errors="coerce")
            out_of_range = ((scores < 0) | (scores > 1)).sum()
            if out_of_range:
                self.fail(f"{label} relevance_score", f"{int(out_of_range)} scores outside [0, 1]")
            else:
                self.pass_(f"{label} relevance_score", "scores in [0, 1] or null")

    def check_labels(self) -> None:
        df = self.load_parquet_dataset("features", "trading_labels")
        cols = [
            "instrument_id",
            "analysis_date",
            "event_time",
            "known_time",
            "horizon_days",
            "future_return",
            "benchmark_return",
            "alpha_return",
            "label_direction",
            "label_version",
        ]
        if not self.require_columns(df, "trading_labels", cols):
            return
        assert df is not None
        self.check_temporal_contract(df, "trading_labels", allow_known_after_scope=True)
        ids = set(df["instrument_id"].astype(str))
        missing = sorted(MVP_SYMBOLS - ids)
        if missing:
            self.fail("trading_labels symbols", f"missing {missing}")
        else:
            self.pass_("trading_labels symbols", sorted(ids).__repr__())
        horizons = set(df["horizon_days"].astype(str))
        expected = {"1d", "5d", "20d"}
        if not expected.issubset(horizons):
            self.fail("trading_labels horizons", f"expected {sorted(expected)}, got {sorted(horizons)}")
        else:
            self.pass_("trading_labels horizons", sorted(horizons).__repr__())
        labels_for_benchmarks = sorted(ids & BENCHMARKS)
        if labels_for_benchmarks:
            self.fail("trading_labels benchmark leakage", f"labels generated for benchmarks: {labels_for_benchmarks}")
        else:
            self.pass_("trading_labels benchmark leakage", "none")

    def check_snapshots(self) -> None:
        path = DATA_DIR / "snapshots" / "agent_input_snapshots" / "snapshots.jsonl"
        if not path.exists():
            self.fail("agent_input_snapshots", f"missing {path}")
            return
        rows = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if line.strip():
                        item = json.loads(line)
                        item["_line_no"] = line_no
                        rows.append(item)
        except Exception as exc:  # noqa: BLE001
            self.fail("agent_input_snapshots", f"invalid JSONL: {exc}")
            return
        if not rows:
            self.fail("agent_input_snapshots", "zero rows")
            return
        df = pd.DataFrame(rows)
        required = [
            "snapshot_id",
            "dataset_version",
            "instrument_id",
            "symbol",
            "analysis_time",
            "lookback_start_time",
            "lookback_end_time",
            "market_window_ref",
            "technical_snapshot_ref",
            "coverage_json",
            "snapshot_version",
            "created_at",
        ]
        missing = [c for c in required if c not in df.columns]
        if missing:
            self.fail("agent_input_snapshots columns", f"missing {missing}")
            return
        self.pass_("agent_input_snapshots columns", f"columns ok ({len(df)} rows)")
        if df["snapshot_id"].duplicated().any():
            self.fail("agent_input_snapshots primary key", "duplicate snapshot_id")
        else:
            self.pass_("agent_input_snapshots primary key", "unique snapshot_id")
        ids = set(df["instrument_id"].astype(str))
        missing_symbols = sorted(MVP_SYMBOLS - ids)
        if missing_symbols:
            self.fail("agent_input_snapshots symbols", f"missing {missing_symbols}")
        else:
            self.pass_("agent_input_snapshots symbols", sorted(ids).__repr__())
        analysis_time = pd.to_datetime(df["analysis_time"], utc=True, errors="coerce")
        if analysis_time.isna().any():
            self.fail("agent_input_snapshots analysis_time", "unparseable/null analysis_time")
        else:
            before = int((analysis_time < DATASET_START).sum())
            after = int((analysis_time > DATASET_END).sum())
            if before or after:
                self.fail("agent_input_snapshots analysis_time range", f"{before} before start, {after} after end")
            else:
                self.pass_("agent_input_snapshots analysis_time range", "within output scope")
        for ref_col in [c for c in df.columns if c.endswith("_ref")]:
            missing_cutoff = ~df[ref_col].astype(str).str.contains("known_time<=", regex=False, na=False)
            if missing_cutoff.any():
                self.warn(f"snapshot ref cutoff {ref_col}", f"{int(missing_cutoff.sum())} refs do not include known_time<= filter")
            else:
                self.pass_(f"snapshot ref cutoff {ref_col}", "all refs include known_time<=")
        bad_coverage = 0
        for value in df["coverage_json"]:
            try:
                json.loads(value) if isinstance(value, str) else value
            except Exception:
                bad_coverage += 1
        if bad_coverage:
            self.fail("agent_input_snapshots coverage_json", f"{bad_coverage} invalid coverage_json values")
        else:
            self.pass_("agent_input_snapshots coverage_json", "valid JSON")

    def check_audit_logs(self) -> None:
        log_dir = DATA_DIR / "experiments" / "crawl_jobs"
        if not log_dir.exists():
            self.fail("crawl_jobs", f"missing {log_dir}")
            return
        files = list(log_dir.glob("*.json"))
        if not files:
            self.fail("crawl_jobs", "no crawl job logs")
            return
        required = {"job_id", "dataset_name", "source", "status", "records_written", "coverage_status"}
        missing_files = []
        bad_json = []
        statuses = set()
        for file in files:
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
            except Exception:
                bad_json.append(file.name)
                continue
            missing = required - set(payload)
            if missing:
                missing_files.append(f"{file.name}: {sorted(missing)}")
            statuses.add(str(payload.get("status")))
        if bad_json:
            self.fail("crawl_jobs JSON", f"invalid JSON files: {bad_json}")
        else:
            self.pass_("crawl_jobs JSON", f"{len(files)} logs")
        if missing_files:
            self.fail("crawl_jobs schema", "; ".join(missing_files[:5]))
        else:
            self.pass_("crawl_jobs schema", "required fields present")
        self.pass_("crawl_jobs statuses", ", ".join(sorted(statuses)))

    def run(self) -> int:
        self.check_manifest()
        self.check_calendar()
        self.check_instrument_master()
        self.check_price_daily()
        self.check_technical_indicators()
        self.check_optional_tables()
        self.check_labels()
        self.check_snapshots()
        self.check_audit_logs()
        return self.report()

    def report(self) -> int:
        print("\nDataLake validation report")
        print("=" * 32)
        for result in self.results:
            detail = f" - {result.detail}" if result.detail else ""
            print(f"[{result.level}] {result.name}{detail}")
        fail_count = sum(1 for r in self.results if r.level == "FAIL")
        warn_count = sum(1 for r in self.results if r.level == "WARN")
        pass_count = sum(1 for r in self.results if r.level == "PASS")
        print("=" * 32)
        print(f"PASS={pass_count} WARN={warn_count} FAIL={fail_count}")
        return 1 if fail_count else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate DataLake outputs.")
    parser.add_argument(
        "--strict-optional",
        action="store_true",
        help="Fail when optional news/social/macro/fundamental datasets are missing.",
    )
    args = parser.parse_args(argv)
    validator = Validator(strict_optional=args.strict_optional)
    return validator.run()


if __name__ == "__main__":
    raise SystemExit(main())
