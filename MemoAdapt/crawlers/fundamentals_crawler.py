import pandas as pd
import yfinance as yf
import uuid
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import save_parquet
from core.audit import log_crawl_job

def crawl_fundamentals(tickers, known_time_cutoff="2023-12-31 23:59:59"):
    print("Crawling Fundamentals & Financial Statements (Phase 4)...")
    all_statements = []
    all_profiles = []

    for ticker in tickers:
        print(f"Fetching financial statements for {ticker}...")
        try:
            t = yf.Ticker(ticker)

            # yfinance returns DataFrames with dates as columns
            statements_map = {
                "income_statement": t.financials,
                "balance_sheet": t.balance_sheet,
                "cash_flow": t.cashflow
            }

            for statement_type, df in statements_map.items():
                if df is None or df.empty:
                    continue

                # Format: index = line items, columns = dates
                df = df.T.reset_index()
                df.rename(columns={"index": "fiscal_period_end"}, inplace=True)

                # Melt to long format
                melted = df.melt(id_vars=["fiscal_period_end"], var_name="line_item", value_name="value")
                melted["instrument_id"] = ticker
                melted["statement_type"] = statement_type
                melted["period_type"] = "annual" # yfinance default properties are annual
                melted["source"] = "yfinance"
                melted["fetched_at"] = pd.Timestamp.utcnow()

                # TEMPORAL CONTRACT (Fallback for missing filing date)
                # Plan says: period_end + 90 days for annual
                melted["event_time"] = pd.to_datetime(melted["fiscal_period_end"]).dt.tz_localize("UTC")
                melted["known_time"] = melted["event_time"] + pd.Timedelta(days=90)

                all_statements.append(melted)

            # Profile snapshot
            info = t.info
            profile_record = {
                "instrument_id": ticker,
                "symbol_yahoo": ticker,
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": info.get("marketCap"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "event_time": pd.Timestamp.utcnow(),
                "known_time": pd.Timestamp.utcnow(),
                "source": "yfinance",
                "fetched_at": pd.Timestamp.utcnow(),
                "is_current": True,
                "coverage_status": "partial"
            }
            all_profiles.append(profile_record)

        except Exception as e:
            print(f"Error fetching fundamentals for {ticker}: {e}")
            log_crawl_job(str(uuid.uuid4()), "financial_statement_line_items", "yfinance", "failed", 0, str(e), coverage_status="partial")
            continue

    if all_profiles:
        profile_df = pd.DataFrame(all_profiles)
        save_parquet(profile_df, "fundamentals_profile_snapshot", layer="normalized", mode="overwrite")
        log_crawl_job(str(uuid.uuid4()), "fundamentals_profile_snapshot", "yfinance", "succeeded", len(profile_df), coverage_status="ok")
        print(f"Saved {len(profile_df)} profile records.")

    if all_statements:
        final_df = pd.concat(all_statements, ignore_index=True)
        final_df = final_df.dropna(subset=["value"])

        # Apply requested scope cutoff.
        cutoff = pd.Timestamp(known_time_cutoff, tz="UTC")
        final_df = final_df[final_df["known_time"] <= cutoff]

        # Drop naive fiscal_period_end string to keep only temporal timestamps
        final_df.drop(columns=["fiscal_period_end"], inplace=True)

        save_parquet(final_df, "financial_statement_line_items", layer="normalized", partition_cols=["instrument_id"], mode="overwrite")

        log_crawl_job(str(uuid.uuid4()), "financial_statement_line_items", "yfinance", "succeeded", len(final_df), coverage_status="ok")
        print(f"Saved {len(final_df)} fundamental records.")

    # Create empty schema for earnings_events
    earnings_df = pd.DataFrame(columns=[
        "instrument_id", "event_time", "known_time", "event_session", "fiscal_period",
        "eps_estimate", "eps_actual", "revenue_estimate", "revenue_actual",
        "source", "fetched_at", "coverage_status"
    ])
    save_parquet(earnings_df, "earnings_events", layer="normalized", mode="overwrite")
    log_crawl_job(str(uuid.uuid4()), "earnings_events", "yfinance", "succeeded", 0, coverage_status="missing")

if __name__ == "__main__":
    tickers = ["AAPL", "AMZN", "GOOGL"]
    crawl_fundamentals(tickers)
