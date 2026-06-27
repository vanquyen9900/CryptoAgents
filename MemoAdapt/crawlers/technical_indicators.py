import pandas as pd
from stockstats import StockDataFrame
import uuid
import sys
import os
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import save_parquet
from core.audit import log_crawl_job

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def calculate_indicators():
    print("Calculating Technical Indicators (Phase 3)...")
    price_dir = DATA_DIR / "normalized" / "price_daily"
    if not price_dir.exists():
        print("No price_daily data found!")
        return

    try:
        from core.storage import load_dataset
        full_df = load_dataset("price_daily", layer="normalized")
    except FileNotFoundError:
        print("Empty price_daily data.")
        return

    results = []

    for ticker, group in full_df.groupby("instrument_id", observed=True):
        print(f"Processing {ticker}...")
        group = group.sort_values("trade_date").copy()

        # stockstats needs 'amount' or just typical OHLCV.
        # Make a copy for stockstats
        sdf = StockDataFrame.retype(group.copy())

        # Calculate features defined in the plan
        group["close_10_ema"] = sdf["close_10_ema"].values
        group["close_50_sma"] = sdf["close_50_sma"].values
        group["close_200_sma"] = sdf["close_200_sma"].values
        group["rsi_14"] = sdf["rsi_14"].values
        group["macd"] = sdf["macd"].values
        group["macd_signal"] = sdf["macds"].values
        group["macd_hist"] = sdf["macdh"].values
        group["boll_mid"] = sdf["boll"].values
        group["boll_upper"] = sdf["boll_ub"].values
        group["boll_lower"] = sdf["boll_lb"].values
        group["atr_14"] = sdf["atr"].values
        group["vwma_20"] = sdf["vwma_20"].values if "vwma_20" in sdf else None

        # The known_time of an indicator is EXACTLY the known_time of the latest price used.
        group["computed_at"] = pd.Timestamp.utcnow()
        group["code_version"] = "v0.1"

        results.append(group)

    final_df = pd.concat(results, ignore_index=True)

    # Keep only the feature columns + PK + temporal
    cols = [
        "instrument_id", "trade_date", "close_10_ema", "close_50_sma", "close_200_sma",
        "rsi_14", "macd", "macd_signal", "macd_hist", "boll_mid", "boll_upper",
        "boll_lower", "atr_14", "vwma_20", "event_time", "known_time", "computed_at", "code_version"
    ]
    # Filter columns that exist
    final_df = final_df[[c for c in cols if c in final_df.columns]]

    # Save parquet
    save_parquet(final_df, "technical_indicators_daily", layer="features", partition_cols=["instrument_id"], mode="overwrite")

    log_crawl_job(
        job_id=str(uuid.uuid4()),
        dataset_name="technical_indicators_daily",
        source="internal_compute",
        status="succeeded",
        records_written=len(final_df)
    )
    print(f"Saved {len(final_df)} records to technical_indicators_daily.")

if __name__ == "__main__":
    calculate_indicators()
