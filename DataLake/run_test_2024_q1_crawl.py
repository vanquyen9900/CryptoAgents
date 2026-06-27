"""Build a separate held-out 2024 Q1 test dataset.
import os as _os, sys as _sys
_os.environ["PYTHONIOENCODING"] = "utf-8"
if _sys.stdout.encoding != "utf-8":
    _sys.stdout.reconfigure(encoding="utf-8")

Isolation strategy
------------------
All crawlers and builders write to ``DataLake/data_test_2024_q1`` instead of
the default ``DataLake/data``.  This is achieved by monkey-patching the global
``DATA_DIR`` in every module that captures it at import time.  The training data
under ``DataLake/data`` is never touched.

Date ranges
-----------
* Evaluation window : 2024-01-01 → 2024-03-29  (62 trading days)
* OHLCV / calendar  : 2023-01-01 → 2024-05-15  (warmup + 20d-label buffer)
* Technical         : rebuilt from the extended OHLCV above
* News              : 2023-12-01 → 2024-03-29
* Social            : 2023-12-01 → 2024-03-29
* Macro             : 2023-01-01 → 2024-03-29
* Labels            : rebuilt; needs price through 2024-05-15
* Snapshots         : 2024-01-02 → 2024-03-29  (evaluation window only)
* Materialized ctx  : ctx_paper_aligned_v1 for each snapshot

Usage
-----
  conda activate tradingagents
  cd c:\\FPT_Uni\\SU26\\DAT
  python DataLake/run_test_2024_q1_crawl.py [--skip-crawl] [--skip-build]

Options
-------
  --skip-crawl   Skip all crawling steps (use if raw data already downloaded)
  --skip-build   Skip snapshot/episode/materialisation steps
  --dry-run      Print what would run without executing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
TEST_DATA_DIR = BASE_DIR / "data_test_2024_q1"

SYMBOLS = ["AAPL", "AMZN", "GOOGL"]
BENCHMARKS = ["SPY", "QQQ"]
ALL_TICKERS = SYMBOLS + BENCHMARKS

# Evaluation window (the dates we will actually run the tournament on)
EVAL_START = "2024-01-01"
EVAL_END = "2024-03-29"

# OHLCV / calendar go back to 2023-01-01 so technical indicators have
# enough warmup bars (200-day SMA needs ~200 trading rows before 2024-01-01)
# and forward to 2024-05-15 so the 20d labels for 2024-03-29 can be computed.
PRICE_START = "2023-01-01"
PRICE_END = "2024-05-15"          # forward buffer for 20d label
PRICE_CUTOFF = "2024-05-15 23:59:59"

# Context data windows: crawl from 2023-12-01 so look-back windows (30–90 days)
# for news/social are satisfied for the first evaluation date (2024-01-02).
CONTEXT_START = "2023-12-01"
CONTEXT_END = EVAL_END

# Macro series go back to 2023-01-01 for a full-year look-back snapshot.
MACRO_START = "2023-01-01"
MACRO_END = EVAL_END

MACRO_SERIES = [
    "FEDFUNDS", "DGS10", "DGS2", "T10Y2Y",
    "CPIAUCSL", "CPILFESL", "UNRATE", "PAYEMS", "VIXCLS",
]

CONTEXT_POLICY_ID = "ctx_paper_aligned_v1"

# ---------------------------------------------------------------------------
# Isolation: patch every module that captures DATA_DIR at import time
# ---------------------------------------------------------------------------

def _redirect_data_dir() -> None:
    """Monkey-patch storage and audit so all writes go to TEST_DATA_DIR."""
    from core import storage, audit

    # Primary patch
    storage.DATA_DIR = TEST_DATA_DIR

    # Patch audit.log_crawl_job to write job files under the test dir
    def _test_log_crawl_job(
        job_id: str,
        dataset_name: str,
        source: str,
        status: str,
        records_written: int,
        records_read: int = 0,
        error: str = "",
        error_count: int = 0,
        retry_count: int = 0,
        fallback_used: bool = False,
        fallback_reason: str = "",
        coverage_status: str = "ok",
        started_at: str | None = None,
    ) -> None:
        log_dir = TEST_DATA_DIR / "experiments" / "crawl_jobs"
        log_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "job_id": job_id,
            "dataset_name": dataset_name,
            "source": source,
            "status": status,
            "records_read": records_read,
            "records_written": records_written,
            "error_count": error_count,
            "retry_count": retry_count,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "coverage_status": coverage_status,
            "error": error,
            "started_at": started_at or pd.Timestamp.utcnow().isoformat(),
            "finished_at": pd.Timestamp.utcnow().isoformat(),
        }
        with (log_dir / f"{job_id}.json").open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)

    audit.log_crawl_job = _test_log_crawl_job

    # Patch modules that cache DATA_DIR at import time
    import crawlers.technical_indicators as _ti
    import builders.snapshot_builder as _sb
    import builders.materialize_inputs_paper_aligned as _mi
    import builders.labels_builder as _lb
    import builders.memo_episode_builder as _eb

    _ti.DATA_DIR = TEST_DATA_DIR
    _sb.DATA_DIR = TEST_DATA_DIR
    _mi.DATA_DIR = TEST_DATA_DIR
    _lb.DATA_DIR = TEST_DATA_DIR
    _eb.DATA_DIR = TEST_DATA_DIR

    print(f"[isolation] All writes redirected to: {TEST_DATA_DIR}")


# ---------------------------------------------------------------------------
# Ensure context_policies.json exists in the test dir
# ---------------------------------------------------------------------------

def _ensure_context_policy() -> None:
    """Copy context_policies.json from the training data dir if not present."""
    src = BASE_DIR / "data" / "memo_adaptation" / "context_policies" / "context_policies.json"
    dst_dir = TEST_DATA_DIR / "memo_adaptation" / "context_policies"
    dst = dst_dir / "context_policies.json"
    if dst.exists():
        return
    if not src.exists():
        print(f"[warn] Context policy not found at {src}. Materialisation may fail.")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(src, dst)
    print(f"[isolation] Copied context_policies.json → {dst}")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _write_manifest() -> None:
    manifest_dir = TEST_DATA_DIR / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset_version": "test_2024_q1_v1",
        "data_split": "test",
        "purpose": "held_out_backtest_evaluation",
        "symbols": SYMBOLS,
        "benchmarks": BENCHMARKS,
        "evaluation_start_date": EVAL_START,
        "evaluation_end_date": EVAL_END,
        "price_start_date": PRICE_START,
        "price_end_date": PRICE_END,
        "context_start_date": CONTEXT_START,
        "macro_start_date": MACRO_START,
        "context_policy_id": CONTEXT_POLICY_ID,
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "notes": [
            "This split is isolated from DataLake/data — training data is never overwritten.",
            "OHLCV/calendar run from 2023-01-01 to provide SMA-200 warmup and 20d label buffer.",
            "News/social crawled from 2023-12-01 to satisfy look-back windows on 2024-01-02.",
            "Do NOT use this split to train memory banks or tune prompts.",
        ],
    }
    with (manifest_dir / "dataset_manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, default=str)
        fh.write("\n")
    print(f"[manifest] Written to {manifest_dir / 'dataset_manifest.json'}")


# ---------------------------------------------------------------------------
# Step runners
# ---------------------------------------------------------------------------

def step_calendar() -> None:
    print("\n" + "=" * 60)
    print(f"STEP 1: Calendar  [{PRICE_START} → {PRICE_END}]")
    print("=" * 60)
    from crawlers.calendar_crawler import crawl_calendar
    crawl_calendar(start_date=PRICE_START, end_date=PRICE_END)


def step_instrument_master() -> None:
    print("\n" + "=" * 60)
    print("STEP 2: Instrument Master")
    print("=" * 60)
    from crawlers.instrument_master_crawler import crawl_instrument_master
    crawl_instrument_master(ALL_TICKERS)


def step_ohlcv() -> None:
    print("\n" + "=" * 60)
    print(f"STEP 3: OHLCV  [{PRICE_START} → {PRICE_END}]  (includes warmup + 20d label buffer)")
    print("=" * 60)
    from crawlers.ohlcv_crawler import crawl_ohlcv
    crawl_ohlcv(
        ALL_TICKERS,
        start_date=PRICE_START,
        end_date=PRICE_END,
        known_time_cutoff=PRICE_CUTOFF,
    )


def step_technical() -> None:
    print("\n" + "=" * 60)
    print("STEP 4: Technical Indicators  (rebuild from OHLCV above)")
    print("=" * 60)
    from crawlers.technical_indicators import calculate_indicators
    calculate_indicators()


def step_fundamentals() -> None:
    print("\n" + "=" * 60)
    print(f"STEP 5: Fundamentals  (cutoff={EVAL_END})")
    print("=" * 60)
    from crawlers.fundamentals_crawler import crawl_fundamentals
    crawl_fundamentals(SYMBOLS, known_time_cutoff=f"{EVAL_END} 23:59:59")


def step_news() -> None:
    print("\n" + "=" * 60)
    print(f"STEP 6: News  [{CONTEXT_START} → {CONTEXT_END}]")
    print("=" * 60)
    from crawlers.news_crawler import crawl_news
    crawl_news(
        SYMBOLS,
        start_date=CONTEXT_START,
        end_date=CONTEXT_END,
        known_time_cutoff=f"{CONTEXT_END} 23:59:59",
    )


def step_social() -> None:
    print("\n" + "=" * 60)
    print(f"STEP 7: Social Proxy  [{CONTEXT_START} → {CONTEXT_END}]")
    print("=" * 60)
    from crawlers.social_crawler import crawl_social
    crawl_social(
        tickers=SYMBOLS,
        start_date=CONTEXT_START,
        end_date=CONTEXT_END,
        known_time_cutoff=f"{CONTEXT_END} 23:59:59",
    )


def step_macro() -> None:
    print("\n" + "=" * 60)
    print(f"STEP 8: Macro Series  [{MACRO_START} → {MACRO_END}]")
    print("=" * 60)
    from crawlers.macro_crawler import crawl_macro
    crawl_macro(
        MACRO_SERIES,
        start_date=MACRO_START,
        end_date=MACRO_END,
        known_time_cutoff=f"{MACRO_END} 23:59:59",
    )


def step_labels() -> None:
    print("\n" + "=" * 60)
    print("STEP 9: Labels  (rebuild; price extends to 2024-05-15 for 20d buffer)")
    print("=" * 60)
    from builders.labels_builder import build_labels
    build_labels()


def step_snapshots() -> None:
    print("\n" + "=" * 60)
    print(f"STEP 10: Snapshots  [{EVAL_START} → {EVAL_END}]  (evaluation window only)")
    print("=" * 60)
    from builders.snapshot_builder import build_snapshots
    build_snapshots(start_date=EVAL_START, end_date=EVAL_END, tickers=SYMBOLS)


def step_episodes() -> None:
    print("\n" + "=" * 60)
    print("STEP 11: Episodes")
    print("=" * 60)
    from builders.memo_episode_builder import build_episodes
    build_episodes()


def step_materialize() -> None:
    print("\n" + "=" * 60)
    print(f"STEP 12: Materialize Inputs  (policy={CONTEXT_POLICY_ID})")
    print("=" * 60)
    _ensure_context_policy()
    from builders.materialize_inputs_paper_aligned import materialize_inputs
    import argparse as _ap
    args = _ap.Namespace(context_policy_id=CONTEXT_POLICY_ID)
    materialize_inputs(args)


# ---------------------------------------------------------------------------
# Dry-run helper
# ---------------------------------------------------------------------------

def _dry_run(skip_crawl: bool, skip_build: bool) -> None:
    print("\n[dry-run] The following steps would run:\n")
    if not skip_crawl:
        print("  STEP 1  : calendar_crawler          2023-01-01 -> 2024-05-15")
        print("  STEP 2  : instrument_master_crawler  AAPL AMZN GOOGL SPY QQQ")
        print("  STEP 3  : ohlcv_crawler              2023-01-01 -> 2024-05-15")
        print("  STEP 4  : technical_indicators       rebuild from OHLCV")
        print("  STEP 5  : fundamentals_crawler       cutoff=2024-03-29")
        print("  STEP 6  : news_crawler               2023-12-01 -> 2024-03-29")
        print("  STEP 7  : social_crawler             2023-12-01 -> 2024-03-29")
        print("  STEP 8  : macro_crawler              2023-01-01 -> 2024-03-29")
        print("  STEP 9  : labels_builder             rebuild")
    if not skip_build:
        print("  STEP 10 : snapshot_builder           2024-01-01 -> 2024-03-29")
        print("  STEP 11 : episode_builder            (from snapshots)")
        print("  STEP 12 : materialize_inputs         ctx_paper_aligned_v1")
    print(f"\nAll output -> {TEST_DATA_DIR}")
    print("Training data under DataLake/data is NOT touched.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(skip_crawl: bool = False, skip_build: bool = False, dry_run: bool = False) -> None:
    print("=" * 60)
    print("MeMo Test-Set Builder: test_2024_q1")
    print(f"  Evaluation : {EVAL_START} -> {EVAL_END}")
    print(f"  OHLCV/Cal  : {PRICE_START} -> {PRICE_END}  (warmup + 20d buffer)")
    print(f"  News/Social: {CONTEXT_START} -> {CONTEXT_END}")
    print(f"  Macro      : {MACRO_START} -> {MACRO_END}")
    print(f"  Output dir : {TEST_DATA_DIR}")
    print(f"  Options    : skip_crawl={skip_crawl}, skip_build={skip_build}, dry_run={dry_run}")
    print("=" * 60)

    if dry_run:
        _dry_run(skip_crawl, skip_build)
        return

    # Redirect all writes BEFORE any crawler/builder is imported
    _redirect_data_dir()
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Phase A: Crawl
    # -----------------------------------------------------------------------
    if not skip_crawl:
        step_calendar()
        step_instrument_master()
        step_ohlcv()
        step_technical()
        step_fundamentals()
        step_news()
        step_social()
        step_macro()
        step_labels()
    else:
        print("\n[skip-crawl] Skipping all crawl steps.")

    # -----------------------------------------------------------------------
    # Phase B: Build
    # -----------------------------------------------------------------------
    if not skip_build:
        step_snapshots()
        step_episodes()
        step_materialize()
    else:
        print("\n[skip-build] Skipping snapshot/episode/materialisation steps.")

    _write_manifest()

    print("\n" + "=" * 60)
    print("DONE — held-out test split ready at:")
    print(f"  {TEST_DATA_DIR}")
    print()
    print("Verify with:")
    print(f"  python DataLake/tools/health/check_test_split_health.py")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build isolated Q1-2024 test dataset for MeMo evaluation."
    )
    parser.add_argument(
        "--skip-crawl",
        action="store_true",
        help="Skip all crawl steps (assumes raw/normalised data already exists in test dir).",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip snapshot, episode and materialisation steps.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run without executing anything.",
    )
    args = parser.parse_args()
    run(skip_crawl=args.skip_crawl, skip_build=args.skip_build, dry_run=args.dry_run)
