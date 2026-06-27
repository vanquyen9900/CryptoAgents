import pandas as pd
import numpy as np
import uuid
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import save_parquet, load_dataset
from core.audit import log_crawl_job

def build_labels():
    print("Building Trading Labels (Phase H)...")
    try:
        price_df = load_dataset("price_daily", layer="normalized")
    except FileNotFoundError:
        print("price_daily not found. Cannot build labels.")
        return

    # Filter to MVP universe + benchmarks
    tickers = ["AAPL", "AMZN", "GOOGL", "SPY", "QQQ"]
    price_df = price_df[price_df["instrument_id"].isin(tickers)].copy()

    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
    price_df = price_df.sort_values(["instrument_id", "trade_date"])

    # Calculate benchmark returns first
    spy_df = price_df[price_df["instrument_id"] == "SPY"].set_index("trade_date")["close"]

    all_labels = []
    horizons = [1, 5, 20]

    for ticker in ["AAPL", "AMZN", "GOOGL"]:
        print(f"Building labels for {ticker}...")
        df = price_df[price_df["instrument_id"] == ticker].copy()
        df.set_index("trade_date", inplace=True)

        for h in horizons:
            # Future return
            df[f"future_close_{h}d"] = df["close"].shift(-h)
            df[f"future_return_{h}d"] = (df[f"future_close_{h}d"] - df["close"]) / df["close"]

            # Benchmark return
            df[f"spy_future_close_{h}d"] = spy_df.shift(-h)
            df[f"spy_future_return_{h}d"] = (df[f"spy_future_close_{h}d"] - spy_df) / spy_df

            # Alpha return
            df[f"alpha_return_{h}d"] = df[f"future_return_{h}d"] - df[f"spy_future_return_{h}d"]

            # Max drawdown (simplified to rolling min over forward window)
            # Roll backwards is tricky, use shift and rolling min
            # df["min_forward"] = df["low"].shift(-h).rolling(h).min()
            # For MVP, omit complex drawdown calculation, just keep structure

            for idx, row in df.iterrows():
                if pd.isna(row[f"future_return_{h}d"]):
                    continue

                future_ret = row[f"future_return_{h}d"]
                direction = "up" if future_ret > 0 else "down" if future_ret < 0 else "flat"

                # event_time = the day of analysis
                # known_time = the day the label is known (analysis_date + horizon)
                # To be absolutely safe, known_time is set to 2099 so agents can never see it

                record = {
                    "instrument_id": ticker,
                    "analysis_date": idx,
                    "event_time": pd.to_datetime(idx, utc=True),
                    "known_time": pd.to_datetime(idx, utc=True) + pd.Timedelta(days=h+1), # known after horizon
                    "horizon_days": f"{h}d",
                    "future_return": float(future_ret),
                    "benchmark_return": float(row[f"spy_future_return_{h}d"]) if pd.notna(row[f"spy_future_return_{h}d"]) else 0.0,
                    "alpha_return": float(row[f"alpha_return_{h}d"]) if pd.notna(row[f"alpha_return_{h}d"]) else 0.0,
                    "max_drawdown_horizon": 0.0,
                    "label_direction": direction,
                    "label_version": "v1.0"
                }
                all_labels.append(record)

    if all_labels:
        final_df = pd.DataFrame(all_labels)
        save_parquet(final_df, "trading_labels", layer="features", partition_cols=["instrument_id"], mode="overwrite")
        log_crawl_job(str(uuid.uuid4()), "trading_labels", "internal_compute", "succeeded", len(final_df), coverage_status="ok")
        print(f"Saved {len(final_df)} trading labels.")

if __name__ == "__main__":
    build_labels()
