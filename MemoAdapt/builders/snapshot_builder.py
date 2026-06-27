import pandas as pd
import uuid
import sys
import os
import json
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import load_dataset, DATA_DIR
from core.audit import log_crawl_job

def build_snapshots(start_date="2019-01-01", end_date="2023-12-31", tickers=None):
    print("Building Agent Input Snapshots (Phase I)...")
    try:
        price_df = load_dataset("price_daily", layer="normalized")
        calendar_df = load_dataset("trading_calendar", layer="normalized")
    except FileNotFoundError:
        print("Required base data missing (price or calendar).")
        return

    tickers = tickers or ["AAPL", "AMZN", "GOOGL"]
    start_date = pd.Timestamp(start_date)
    end_date = pd.Timestamp(end_date)

    # Filter calendar for trading days within our scope
    cal = calendar_df[(calendar_df["is_trading_day"] == True)]
    cal["date"] = pd.to_datetime(cal["date"])
    valid_dates = cal[(cal["date"] >= start_date) & (cal["date"] <= end_date)]["date"].tolist()

    all_snapshots = []

    for ticker in tickers:
        print(f"Building snapshots for {ticker}...")
        for date in valid_dates:
            analysis_time_str = f"{date.strftime('%Y-%m-%d')} 16:00:00"
            analysis_time = pd.Timestamp(analysis_time_str, tz="America/New_York").tz_convert("UTC")

            # This is just a metadata index mapping back to the Data Lake
            # The actual agents will query the Data Lake where known_time <= analysis_time
            record = {
                "snapshot_id": str(uuid.uuid4()),
                "dataset_version": "v0.1",
                "instrument_id": ticker,
                "symbol": ticker,
                "analysis_time": analysis_time.isoformat(),
                "lookback_start_time": (analysis_time - pd.Timedelta(days=365)).isoformat(), # 1 yr lookback
                "lookback_end_time": analysis_time.isoformat(),
                "market_window_ref": f"price_daily?instrument_id={ticker}&known_time<={analysis_time.isoformat()}",
                "technical_snapshot_ref": f"technical_indicators_daily?instrument_id={ticker}&known_time<={analysis_time.isoformat()}",
                "fundamentals_snapshot_ref": f"fundamentals_profile_snapshot?instrument_id={ticker}&known_time<={analysis_time.isoformat()}",
                "ticker_news_window_ref": f"news_articles?instrument_id={ticker}&known_time<={analysis_time.isoformat()}",
                "macro_news_window_ref": f"macro_news_articles?known_time<={analysis_time.isoformat()}",
                "social_window_ref": f"stocktwits_messages?instrument_id={ticker}&known_time<={analysis_time.isoformat()}",
                "macro_snapshot_ref": f"macro_series_observations?known_time<={analysis_time.isoformat()}",
                "coverage_json": json.dumps({"news": "partial"}),
                "snapshot_version": "v1.0",
                "created_at": pd.Timestamp.utcnow().isoformat()
            }
            all_snapshots.append(record)

    if all_snapshots:
        out_dir = DATA_DIR / "snapshots" / "agent_input_snapshots"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Save JSONL
        out_file = out_dir / "snapshots.jsonl"
        with open(out_file, "w", encoding="utf-8") as f:
            for item in all_snapshots:
                f.write(json.dumps(item) + "\n")

        # Snapshot Manifest
        manifest = {
            "dataset_version": "v0.1",
            "count": len(all_snapshots),
            "generated_at": pd.Timestamp.utcnow().isoformat()
        }
        with open(DATA_DIR / "snapshots" / "snapshot_manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        log_crawl_job(str(uuid.uuid4()), "agent_input_snapshots", "internal_compute", "succeeded", len(all_snapshots), coverage_status="ok")
        print(f"Saved {len(all_snapshots)} snapshots.")

if __name__ == "__main__":
    build_snapshots()
