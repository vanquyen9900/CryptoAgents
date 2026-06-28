import pandas as pd
import pandas_market_calendars as mcal
import uuid
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import save_parquet
from core.audit import log_crawl_job

def crawl_calendar(start_date="2018-01-01", end_date="2023-12-31"):
    print("Crawling NYSE calendar...")
    nyse = mcal.get_calendar('NYSE')
    schedule = nyse.schedule(start_date=start_date, end_date=end_date)

    df = schedule.reset_index()
    # rename index to date
    df.rename(columns={"index": "date"}, inplace=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["calendar_id"] = "NYSE"
    df["is_trading_day"] = True
    df["timezone"] = "America/New_York"
    df["source"] = "pandas_market_calendars"
    df["fetched_at"] = pd.Timestamp.utcnow()

    # Temporal contract
    df["event_time"] = pd.to_datetime(df["date"], utc=True)
    df["known_time"] = df["event_time"] # Calendar is known ahead of time

    df = df[["calendar_id", "date", "is_trading_day", "market_open", "market_close", "timezone", "source", "event_time", "known_time", "fetched_at"]]

    # Validation: No duplicates
    if df.duplicated(subset=["calendar_id", "date"]).any():
        print("Warning: Duplicates found in calendar!")
        df = df.drop_duplicates(subset=["calendar_id", "date"])

    save_parquet(df, "trading_calendar")

    log_crawl_job(
        job_id=str(uuid.uuid4()),
        dataset_name="trading_calendar",
        source="pandas_market_calendars",
        status="succeeded",
        records_written=len(df)
    )
    print(f"Done crawling calendar: {len(df)} days.")

if __name__ == "__main__":
    crawl_calendar()
