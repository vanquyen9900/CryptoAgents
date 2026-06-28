"""Quick health check for the held-out test_2024_q1 dataset.

Run after run_test_2024_q1_crawl.py completes.

  python MemoAdapt/tools/health/check_test_split_health.py
"""
import os, sys, json
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
from collections import Counter
import pandas as pd

DATALAKE_DIR = Path(__file__).resolve().parents[2]
TEST_DIR = DATALAKE_DIR / "data_test_2024_q1"

EVAL_START = pd.Timestamp("2024-01-01")
EVAL_END   = pd.Timestamp("2024-03-29")

total_pass = 0
total_fail = 0
total_warn = 0


def check(label, condition, detail=""):
    global total_pass, total_fail
    status = "[PASS]" if condition else "[FAIL]"
    if condition:
        total_pass += 1
    else:
        total_fail += 1
    suffix = f" -- {detail}" if detail else ""
    print(f"  {status} {label}{suffix}")
    return condition


def warn(label, detail=""):
    global total_warn
    total_warn += 1
    suffix = f" -- {detail}" if detail else ""
    print(f"  [WARN] {label}{suffix}")


def info(label, detail=""):
    suffix = f" -- {detail}" if detail else ""
    print(f"  [INFO] {label}{suffix}")


def section(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")


def load_parquet_safe(path: Path):
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path, engine="pyarrow")


def load_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# 1. Manifest
# ---------------------------------------------------------------------------
section("1. Manifest")
manifest_path = TEST_DIR / "manifests" / "dataset_manifest.json"
check("manifest.json exists", manifest_path.exists())
if manifest_path.exists():
    m = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    check("data_split = test", m.get("data_split") == "test", str(m.get("data_split")))
    check("evaluation_start_date = 2024-01-01", m.get("evaluation_start_date") == "2024-01-01")
    check("evaluation_end_date   = 2024-03-29", m.get("evaluation_end_date") == "2024-03-29")
    check("price_start_date = 2023-01-01", m.get("price_start_date") == "2023-01-01")
    check("price_end_date = 2024-05-15", m.get("price_end_date") == "2024-05-15")

# ---------------------------------------------------------------------------
# 2. Calendar
# ---------------------------------------------------------------------------
section("2. Trading Calendar")
cal_path = TEST_DIR / "normalized" / "trading_calendar"
cal = load_parquet_safe(cal_path)
check("trading_calendar exists", not cal.empty, f"{len(cal)} rows")
if not cal.empty:
    cal["date"] = pd.to_datetime(cal["date"])
    trading_days = cal[cal["is_trading_day"] == True]["date"]
    eval_days = trading_days[(trading_days >= EVAL_START) & (trading_days <= EVAL_END)]
    check("Calendar covers 2024-01-02", trading_days.min() <= pd.Timestamp("2024-01-02"), str(trading_days.min())[:10])
    check("Calendar covers 2024-05-15", trading_days.max() >= pd.Timestamp("2024-05-15"), str(trading_days.max())[:10])
    check("Eval trading days count = ~62", 55 <= len(eval_days) <= 70, f"got {len(eval_days)}")
    info("Total trading days in test dir", str(len(trading_days)))
    info("Eval range trading days", str(len(eval_days)))

# ---------------------------------------------------------------------------
# 3. OHLCV / Price
# ---------------------------------------------------------------------------
section("3. OHLCV / Price Daily")
price_path = TEST_DIR / "normalized" / "price_daily"
price = load_parquet_safe(price_path)
check("price_daily exists", not price.empty, f"{len(price)} rows")
if not price.empty:
    price["trade_date"] = pd.to_datetime(price["trade_date"])
    syms = price["instrument_id"].unique().tolist()
    info("Symbols present", str(sorted(syms)))
    for sym in ["AAPL", "AMZN", "GOOGL"]:
        sym_df = price[price["instrument_id"] == sym]
        max_date = sym_df["trade_date"].max()
        min_date = sym_df["trade_date"].min()
        check(f"{sym}: price from <= 2023-01-03", min_date <= pd.Timestamp("2023-01-03"), str(min_date)[:10])
        check(f"{sym}: price through >= 2024-04-30", max_date >= pd.Timestamp("2024-04-30"), str(max_date)[:10])

# ---------------------------------------------------------------------------
# 4. Technical Indicators
# ---------------------------------------------------------------------------
section("4. Technical Indicators Daily")
tech_path = TEST_DIR / "features" / "technical_indicators_daily"
tech = load_parquet_safe(tech_path)
check("technical_indicators_daily exists", not tech.empty, f"{len(tech)} rows")
if not tech.empty:
    tech["trade_date"] = pd.to_datetime(tech["trade_date"])
    for sym in ["AAPL", "AMZN", "GOOGL"]:
        s = tech[tech["instrument_id"] == sym]
        if not s.empty:
            max_date = s["trade_date"].max()
            check(f"{sym}: tech indicators through >= 2024-03-29", max_date >= pd.Timestamp("2024-03-29"), str(max_date)[:10])
    # Check SMA200 is not null for eval days (needs 200 prior rows)
    eval_tech = tech[tech["trade_date"] >= EVAL_START]
    if "sma_200" in tech.columns:
        null_sma = eval_tech["sma_200"].isna().sum()
        check("SMA200 not null in eval window", null_sma == 0, f"{null_sma} null rows")

# ---------------------------------------------------------------------------
# 5. News
# ---------------------------------------------------------------------------
section("5. News Articles")
news_path = TEST_DIR / "normalized" / "news_articles"
news = load_parquet_safe(news_path)
if news.empty:
    warn("news_articles empty (may be ok if Alpaca key unavailable)")
else:
    news["known_time"] = pd.to_datetime(news["known_time"], utc=True)
    eval_news = news[news["known_time"] >= pd.Timestamp("2024-01-01", tz="UTC")]
    check("News exists for eval period", len(eval_news) > 0, f"{len(eval_news)} articles in Jan-Mar 2024")
    sym_counts = Counter(news["instrument_id"].tolist())
    info("News by symbol", str(dict(sym_counts)))

# ---------------------------------------------------------------------------
# 6. Social Sentiment
# ---------------------------------------------------------------------------
section("6. Social Sentiment Daily")
soc_path = TEST_DIR / "features" / "social_sentiment_daily"
soc = load_parquet_safe(soc_path)
if soc.empty:
    warn("social_sentiment_daily empty (may be ok if Alpha Vantage key unavailable)")
else:
    soc["date"] = pd.to_datetime(soc["date"])
    eval_soc = soc[(soc["date"] >= EVAL_START) & (soc["date"] <= EVAL_END)]
    check("Social exists for eval period", len(eval_soc) > 0, f"{len(eval_soc)} rows")
    info("Social rows by symbol", str(Counter(soc["instrument_id"].tolist())))

# ---------------------------------------------------------------------------
# 7. Macro
# ---------------------------------------------------------------------------
section("7. Macro Series Observations")
macro_path = TEST_DIR / "normalized" / "macro_series_observations"
macro = load_parquet_safe(macro_path)
check("macro_series_observations exists", not macro.empty, f"{len(macro)} rows")
if not macro.empty:
    series = macro["series_id"].unique().tolist()
    info("Series available", str(sorted(series)))
    check(">=5 macro series", len(series) >= 5, f"got {len(series)}")

# ---------------------------------------------------------------------------
# 8. Labels
# ---------------------------------------------------------------------------
section("8. Trading Labels")
labels_path = TEST_DIR / "features" / "trading_labels"
labels = load_parquet_safe(labels_path)
check("trading_labels exists", not labels.empty, f"{len(labels)} rows")
if not labels.empty:
    labels["analysis_date"] = pd.to_datetime(labels["analysis_date"])
    eval_labels = labels[
        (labels["analysis_date"] >= EVAL_START) &
        (labels["analysis_date"] <= EVAL_END)
    ]
    check("Labels exist for eval window", len(eval_labels) > 0, f"{len(eval_labels)} rows")
    horizons = set(eval_labels["horizon_days"].astype(str).str.replace("d", "").unique().tolist())
    check("Horizons 1, 5, 20 all present", {"1", "5", "20"}.issubset(horizons), str(horizons))
    none_rewards = eval_labels["future_return"].isna().sum()
    check("No null future_return in eval", none_rewards == 0, f"{none_rewards} null rows")

# ---------------------------------------------------------------------------
# 9. Snapshots
# ---------------------------------------------------------------------------
section("9. Agent Input Snapshots")
snap_path = TEST_DIR / "snapshots" / "agent_input_snapshots" / "snapshots.jsonl"
snapshots = load_jsonl(snap_path)
check("snapshots.jsonl exists", snap_path.exists(), f"{len(snapshots)} rows")
if snapshots:
    snap_dates = [s.get("analysis_time", "")[:10] for s in snapshots]
    snap_date_min = min(snap_dates)
    snap_date_max = max(snap_dates)
    check("Snapshots start >= 2024-01-01", snap_date_min >= "2024-01-01", snap_date_min)
    check("Snapshots end = 2024-03-28 (Good Friday 03-29)", snap_date_max == "2024-03-28", snap_date_max)
    sym_counts = Counter(s.get("instrument_id") for s in snapshots)
    info("Snapshots per symbol", str(dict(sym_counts)))
    # Each symbol should have ~62 trading days
    for sym in ["AAPL", "AMZN", "GOOGL"]:
        n = sym_counts.get(sym, 0)
        check(f"{sym}: snapshots count ~62", 55 <= n <= 70, f"got {n}")

# ---------------------------------------------------------------------------
# 10. Episodes
# ---------------------------------------------------------------------------
section("10. Trading Episodes")
ep_path = TEST_DIR / "memo_adaptation" / "episodes" / "trading_episodes.jsonl"
episodes = load_jsonl(ep_path)
check("trading_episodes.jsonl exists", ep_path.exists(), f"{len(episodes)} rows")
if episodes:
    ep_syms = Counter(e.get("symbol") for e in episodes)
    info("Episodes per symbol", str(dict(ep_syms)))
    for sym in ["AAPL", "AMZN", "GOOGL"]:
        n = ep_syms.get(sym, 0)
        check(f"{sym}: episodes count ~62", 55 <= n <= 70, f"got {n}")

# ---------------------------------------------------------------------------
# 11. Materialized Inputs
# ---------------------------------------------------------------------------
section("11. Materialized Inputs (ctx_paper_aligned_v1)")
inputs_path = TEST_DIR / "memo_adaptation" / "materialized_inputs" / "inputs_ctx_paper_aligned_v1.jsonl"
inputs = load_jsonl(inputs_path)
check("inputs_ctx_paper_aligned_v1.jsonl exists", inputs_path.exists(), f"{len(inputs)} rows")
if inputs:
    total_expected = len(episodes) if episodes else 186  # 3 symbols * ~62 days
    check("Input count matches episode count", abs(len(inputs) - total_expected) <= 5,
          f"inputs={len(inputs)}, episodes={total_expected}")
    has_market = sum(1 for r in inputs if r.get("market_window") and len(r["market_window"]) > 0)
    has_tech   = sum(1 for r in inputs if r.get("technical_window") and len(r["technical_window"]) > 0)
    has_macro  = sum(1 for r in inputs if r.get("macro_snapshot") and len(r["macro_snapshot"]) > 0)
    has_social = sum(1 for r in inputs if r.get("social_window") and len(r["social_window"]) > 0)
    has_news   = sum(1 for r in inputs if r.get("ticker_news_window") and len(r["ticker_news_window"]) > 0)
    n = len(inputs)
    check(f"market_window = {n}", has_market == n, f"got {has_market}")
    check(f"technical_window = {n}", has_tech == n, f"got {has_tech}")
    check(f"macro_snapshot = {n}", has_macro == n, f"got {has_macro}")
    if has_social == 0:
        warn("social_window = 0 (ok if Alpha Vantage key unavailable)")
    else:
        info("social_window coverage", str(has_social))
    if has_news == 0:
        warn("ticker_news_window = 0 (ok if Alpaca key unavailable)")
    else:
        info("ticker_news_window coverage", str(has_news))

# ---------------------------------------------------------------------------
# 12. Isolation check — training data not touched
# ---------------------------------------------------------------------------
section("12. Isolation Check (training data unmodified)")
train_eps_path = DATALAKE_DIR / "data" / "memo_adaptation" / "episodes" / "trading_episodes.jsonl"
if train_eps_path.exists():
    train_eps = load_jsonl(train_eps_path)
    # Ensure no 2024 dates leaked into training episodes
    train_2024 = [e for e in train_eps if e.get("analysis_date", "")[:4] == "2024"]
    check("No 2024 dates in training episodes", len(train_2024) == 0,
          f"found {len(train_2024)} leaked rows")
    info("Training episodes total", str(len(train_eps)))
else:
    warn("Training episodes file not found (cannot verify isolation)")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section("OVERALL SUMMARY")
print(f"  Passed:   {total_pass}")
print(f"  Failed:   {total_fail}")
print(f"  Warnings: {total_warn}")
print()
if total_fail == 0:
    print("  ALL CHECKS PASSED -- test split is ready for tournament evaluation!")
else:
    print(f"  {total_fail} CHECKS FAILED -- review above before running tournament")
    sys.exit(1)
