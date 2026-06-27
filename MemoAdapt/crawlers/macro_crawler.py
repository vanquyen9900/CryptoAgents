import pandas as pd
import requests
import uuid
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import save_parquet
from core.audit import log_crawl_job
from core.temporal import get_known_time_for_macro

FRED_KEY = os.environ.get("FRED_API_KEY")

def crawl_macro(series_ids, start_date="2018-01-01", end_date="2023-12-31", known_time_cutoff=None):
    print("Crawling Macro Series (Phase G)...")
    if not FRED_KEY:
        print("FRED_API_KEY not found in env. Logging coverage gap.")
        empty_df = pd.DataFrame(columns=[
            "series_id", "observation_date", "value", "event_time", "known_time",
            "source", "fetched_at", "coverage_status"
        ])
        save_parquet(empty_df, "macro_series_observations", layer="normalized", mode="overwrite")
        log_crawl_job(str(uuid.uuid4()), "macro_series_observations", "fred", "failed", 0, "Missing API Key", coverage_status="missing")
        return

    all_records = []

    for series in series_ids:
        print(f"Fetching macro series: {series}")
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series,
            "api_key": FRED_KEY,
            "file_type": "json",
            "observation_start": start_date,
            "observation_end": end_date
        }
        try:
            res = requests.get(url, params=params)
            if res.status_code != 200:
                print(f"Error fetching {series}: {res.text}")
                continue

            data = res.json()
            observations = data.get("observations", [])

            for obs in observations:
                if obs["value"] == ".":
                    continue # empty value in FRED

                obs_date = obs["date"]
                record = {
                    "series_id": series,
                    "observation_date": obs_date,
                    "value": float(obs["value"]),
                    "event_time": pd.to_datetime(obs_date, utc=True),
                    "known_time": get_known_time_for_macro(obs_date),
                    "source": "fred",
                    "fetched_at": pd.Timestamp.utcnow()
                }
                all_records.append(record)

        except Exception as e:
            print(f"Exception fetching {series}: {e}")

    if all_records:
        df = pd.DataFrame(all_records)

        # Apply requested scope cutoff.
        cutoff_value = known_time_cutoff or f"{end_date} 23:59:59"
        cutoff = pd.Timestamp(cutoff_value, tz="UTC")
        df = df[df["known_time"] <= cutoff]

        save_parquet(df, "macro_series_observations", layer="normalized", partition_cols=["series_id"], mode="overwrite")
        log_crawl_job(str(uuid.uuid4()), "macro_series_observations", "fred", "succeeded", len(df), coverage_status="ok")
        print(f"Saved {len(df)} macro observations.")
    else:
        empty_df = pd.DataFrame(columns=[
            "series_id", "observation_date", "value", "event_time", "known_time",
            "source", "fetched_at", "coverage_status"
        ])
        save_parquet(empty_df, "macro_series_observations", layer="normalized", mode="overwrite")
        log_crawl_job(str(uuid.uuid4()), "macro_series_observations", "fred", "succeeded", 0, coverage_status="missing")

if __name__ == "__main__":
    series = ["FEDFUNDS", "DGS10", "DGS2", "T10Y2Y", "CPIAUCSL", "CPILFESL", "UNRATE", "PAYEMS", "VIXCLS"]
    crawl_macro(series)
