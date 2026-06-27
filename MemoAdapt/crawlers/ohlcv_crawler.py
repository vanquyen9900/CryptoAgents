import pandas as pd
import yfinance as yf
import uuid
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.temporal import get_known_time_for_daily_ohlcv
from core.storage import save_parquet
from core.audit import log_crawl_job

def crawl_ohlcv(tickers, start_date="2018-01-01", end_date="2023-12-31", known_time_cutoff=None):
    # end_date in yfinance is exclusive, so we add 1 day
    yf_end_date = pd.to_datetime(end_date) + pd.Timedelta(days=1)
    yf_end_date_str = yf_end_date.strftime("%Y-%m-%d")

    all_dfs = []

    for ticker in tickers:
        print(f"Crawling OHLCV for {ticker}...")
        try:
            df = yf.download(ticker, start=start_date, end=yf_end_date_str, auto_adjust=False, progress=False)
            if df.empty:
                print(f"No data for {ticker}")
                continue

            # Formatting
            df = df.reset_index()
            # If multi-index (yfinance sometimes does this), flatten it
            if isinstance(df.columns, pd.MultiIndex):
                # drop the second level (ticker) if it exists
                if len(df.columns.levels) > 1:
                    df.columns = df.columns.get_level_values(0)

            # Print columns to debug
            print("Columns from yfinance:", df.columns)

            # yfinance columns are: Date/Datetime, Open, High, Low, Close, Adj Close, Volume
            rename_dict = {}
            for col in df.columns:
                lower_col = col.lower()
                if "date" in lower_col:
                    rename_dict[col] = "date"
                elif "open" == lower_col:
                    rename_dict[col] = "open"
                elif "high" == lower_col:
                    rename_dict[col] = "high"
                elif "low" == lower_col:
                    rename_dict[col] = "low"
                elif "adj close" == lower_col:
                    rename_dict[col] = "adj_close"
                elif "close" == lower_col:
                    rename_dict[col] = "close"
                elif "volume" == lower_col:
                    rename_dict[col] = "volume"

            df.rename(columns=rename_dict, inplace=True)

            df["instrument_id"] = ticker
            df["symbol_yahoo"] = ticker
            df["source"] = "yfinance"
            df["fetched_at"] = pd.Timestamp.utcnow()

            # Temporal Contract
            df["event_time"] = pd.to_datetime(df["date"]).dt.tz_localize("UTC")
            df["known_time"] = pd.to_datetime(df["date"]).apply(get_known_time_for_daily_ohlcv)

            # Safety check according to plan: no known_time beyond the requested scope.
            cutoff_value = known_time_cutoff or f"{end_date} 23:59:59"
            cutoff = pd.Timestamp(cutoff_value, tz="UTC")
            df = df[df["known_time"] <= cutoff]

            # Keep trade_date as date
            df["trade_date"] = pd.to_datetime(df["date"]).dt.date

            # Reorder and ensure columns
            cols = ["instrument_id", "symbol_yahoo", "trade_date", "event_time", "known_time", "open", "high", "low", "close", "adj_close", "volume", "source", "fetched_at"]
            for c in cols:
                if c not in df.columns:
                    df[c] = None
            df = df[cols]

            # Validation: drop duplicates
            if df.duplicated(subset=["instrument_id", "trade_date", "source"]).any():
                df = df.drop_duplicates(subset=["instrument_id", "trade_date", "source"])

            # Validation: no null OHLCV
            df = df.dropna(subset=["open", "high", "low", "close", "volume"])

            all_dfs.append(df)

        except Exception as e:
            print(f"Error crawling {ticker}: {e}")
            log_crawl_job(
                job_id=str(uuid.uuid4()),
                dataset_name="price_daily",
                source="yfinance",
                status="failed",
                records_written=0,
                error=str(e),
                coverage_status="missing"
            )
            continue

    if all_dfs:
        final_df = pd.concat(all_dfs, ignore_index=True)
        final_df = final_df.drop_duplicates(
            subset=["instrument_id", "trade_date", "source"],
            keep="last",
        )
        # Partitioning by instrument_id when saving
        save_parquet(final_df, "price_daily", partition_cols=["instrument_id"], mode="overwrite")

        log_crawl_job(
            job_id=str(uuid.uuid4()),
            dataset_name="price_daily",
            source="yfinance",
            status="succeeded",
            records_written=len(final_df)
        )
        print(f"Saved {len(final_df)} records to price_daily.")

if __name__ == "__main__":
    tickers = ["AAPL", "AMZN", "GOOGL", "SPY", "QQQ"]
    crawl_ohlcv(tickers)
