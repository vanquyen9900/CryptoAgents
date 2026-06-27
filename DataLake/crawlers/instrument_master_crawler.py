import pandas as pd
import yfinance as yf
import uuid
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import save_parquet
from core.audit import log_crawl_job

def crawl_instrument_master(tickers):
    print("Crawling Instrument Master (Phase B)...")
    records = []

    for ticker in tickers:
        print(f"Fetching info for {ticker}...")
        try:
            t = yf.Ticker(ticker)
            info = t.info

            if not info or "symbol" not in info:
                raise ValueError("Empty info from yfinance")

            record = {
                "instrument_id": ticker,
                "symbol_yahoo": info.get("symbol", ticker),
                "asset_type": info.get("quoteType", "EQUITY"),
                "name": info.get("shortName", ticker),
                "exchange": info.get("exchange", "NASDAQ"),
                "currency": info.get("currency", "USD"),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "benchmark_symbol": "SPY" if ticker != "SPY" else "SPY",
                "source": "yfinance",
                "event_time": pd.Timestamp.utcnow(),
                "known_time": pd.Timestamp.utcnow(),
                "fetched_at": pd.Timestamp.utcnow()
            }
            records.append(record)
        except Exception as e:
            print(f"Error fetching info for {ticker}, using fallback. Error: {e}")
            # Fallback static record
            record = {
                "instrument_id": ticker,
                "symbol_yahoo": ticker,
                "asset_type": "ETF" if ticker in ["SPY", "QQQ"] else "EQUITY",
                "name": ticker,
                "exchange": "US Market",
                "currency": "USD",
                "sector": "Unknown",
                "industry": "Unknown",
                "benchmark_symbol": "SPY",
                "source": "static_fallback",
                "event_time": pd.Timestamp.utcnow(),
                "known_time": pd.Timestamp.utcnow(),
                "fetched_at": pd.Timestamp.utcnow()
            }
            records.append(record)
            log_crawl_job(str(uuid.uuid4()), "instrument_master", "yfinance", "failed", 1, error=str(e), fallback_used=True, coverage_status="partial")

    if records:
        df = pd.DataFrame(records)
        save_parquet(df, "instrument_master", layer="normalized")
        log_crawl_job(str(uuid.uuid4()), "instrument_master", "yfinance", "succeeded", len(df), coverage_status="ok")
        print(f"Saved {len(df)} records to instrument_master.")

if __name__ == "__main__":
    tickers = ["AAPL", "AMZN", "GOOGL", "SPY", "QQQ"]
    crawl_instrument_master(tickers)
