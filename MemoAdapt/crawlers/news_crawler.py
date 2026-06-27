import pandas as pd
import yfinance as yf
import requests
import time
import uuid
import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import save_parquet, save_raw_json
from core.audit import log_crawl_job

ALPACA_KEY = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY")

def crawl_alpaca_news(tickers, start_date="2019-01-01", end_date="2023-12-31"):
    url = "https://data.alpaca.markets/v1beta1/news"
    headers = {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET
    }

    all_articles = []

    # Simple probe
    probe_params = {
        "symbols": tickers[0],
        "start": f"{start_date}T00:00:00Z",
        "end": f"{end_date}T23:59:59Z",
        "limit": 10
    }
    probe_res = requests.get(url, headers=headers, params=probe_params)
    if probe_res.status_code != 200:
        print(f"Alpaca probe failed: {probe_res.status_code}. Fallback to yfinance.")
        return None

    print("Alpaca probe successful. Crawling full history...")

    # Crawl month by month to avoid huge payload
    # For MVP we just do a simplified pagination loop per ticker
    for ticker in tickers:
        print(f"Alpaca: Fetching news for {ticker}...")
        page_token = None
        count = 0

        while True:
            params = {
                "symbols": ticker,
                "start": f"{start_date}T00:00:00Z",
                "end": f"{end_date}T23:59:59Z",
                "limit": 50,
                "include_content": "false"
            }
            if page_token:
                params["page_token"] = page_token

            res = requests.get(url, headers=headers, params=params)

            if res.status_code == 429:
                print("Rate limit hit, sleeping 5s...")
                time.sleep(5)
                continue
            elif res.status_code != 200:
                print(f"Error {res.status_code}: {res.text}")
                break

            data = res.json()
            articles = data.get("news", [])

            # Save raw
            req_id = res.headers.get("X-Request-ID", str(uuid.uuid4()))
            save_raw_json(data, "news_articles/source=alpaca", f"{req_id}.json")

            for item in articles:
                pub_time = pd.to_datetime(item.get("created_at"), utc=True)
                record = {
                    "article_id": str(item.get("id", uuid.uuid4())),
                    "instrument_id": ticker,
                    "symbols": ",".join(item.get("symbols", [])),
                    "title": item.get("headline", ""),
                    "summary": item.get("summary", ""),
                    "url": item.get("url", ""),
                    "source_name": item.get("source", "Alpaca"),
                    "vendor": "alpaca",
                    "query_used": ticker,
                    "query_type": "ticker",
                    "query_set_version": "v1",
                    "relevance_score": 1.0,
                    "event_time": pub_time,
                    "known_time": pub_time, # same as publish
                    "source": "alpaca",
                    "fetched_at": pd.Timestamp.utcnow(),
                    "coverage_status": "ok"
                }
                all_articles.append(record)

            count += len(articles)
            page_token = data.get("next_page_token")
            if not page_token:
                break

            time.sleep(0.35) # pacing 180 req/min

        print(f"Fetched {count} articles for {ticker}.")

    return all_articles

def parse_yfinance_pub_time(item):
    if item.get("providerPublishTime"):
        return pd.to_datetime(item["providerPublishTime"], unit="s", utc=True)
    content = item.get("content") or {}
    if content.get("pubDate"):
        return pd.to_datetime(content["pubDate"], utc=True)
    return None

def crawl_yfinance_fallback(tickers):
    print("Crawling News via yfinance fallback (recent only)...")
    all_news = []
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            news_list = t.news
            if not news_list:
                log_crawl_job(str(uuid.uuid4()), "news_articles", "yfinance", "succeeded", 0, coverage_status="missing")
                continue

            for item in news_list:
                pub_time = parse_yfinance_pub_time(item)
                if pub_time is None:
                    continue

                record = {
                    "article_id": item.get("uuid", str(uuid.uuid4())),
                    "instrument_id": ticker,
                    "symbols": ticker,
                    "title": item.get("title", ""),
                    "summary": item.get("relatedTickers", ""),
                    "url": item.get("link", ""),
                    "source_name": item.get("publisher", "Yahoo Finance"),
                    "vendor": "yfinance",
                    "query_used": ticker,
                    "query_type": "ticker",
                    "query_set_version": "v1",
                    "relevance_score": 1.0,
                    "event_time": pub_time,
                    "known_time": pub_time,
                    "source": "yfinance",
                    "fetched_at": pd.Timestamp.utcnow(),
                    "coverage_status": "partial"
                }
                all_news.append(record)
        except Exception as e:
            log_crawl_job(str(uuid.uuid4()), "news_articles", "yfinance", "failed", 0, str(e), coverage_status="missing")
            continue
    return all_news

def crawl_news(tickers, start_date="2019-01-01", end_date="2023-12-31", known_time_cutoff=None):
    print("Crawling News (Phase E)...")
    all_articles = None

    if ALPACA_KEY and ALPACA_SECRET:
        all_articles = crawl_alpaca_news(tickers, start_date=start_date, end_date=end_date)
    else:
        # Log missing Alpaca credentials
        log_crawl_job(str(uuid.uuid4()), "news_articles", "alpaca", "partial", 0, fallback_used=True, fallback_reason="alpaca_empty_probe", coverage_status="missing")

    if not all_articles:
        print("Using fallback to yfinance...")
        all_articles = crawl_yfinance_fallback(tickers)

    if all_articles:
        df = pd.DataFrame(all_articles)

        # Apply requested scope cutoff.
        cutoff_value = known_time_cutoff or f"{end_date} 23:59:59"
        cutoff = pd.Timestamp(cutoff_value, tz="UTC")
        df = df[df["known_time"] <= cutoff]

        # Deduplicate
        if not df.empty:
            df = df.drop_duplicates(subset=["url", "instrument_id"])
            save_parquet(df, "news_articles", layer="normalized", partition_cols=["instrument_id"], mode="overwrite")
            coverage = "ok" if (ALPACA_KEY and ALPACA_SECRET) else "partial"
            log_crawl_job(str(uuid.uuid4()), "news_articles", df["vendor"].iloc[0], "succeeded", len(df), coverage_status=coverage)
            print(f"Saved {len(df)} historical news articles.")
        else:
            print("All returned news articles were outside the requested cutoff. Nothing to save.")
            # Save empty schema
            save_parquet(pd.DataFrame(columns=["article_id", "instrument_id", "symbols", "title", "summary", "url", "source_name", "vendor", "query_used", "query_type", "query_set_version", "relevance_score", "event_time", "known_time", "source", "fetched_at", "coverage_status"]), "news_articles", layer="normalized", mode="overwrite")
            log_crawl_job(str(uuid.uuid4()), "news_articles", "fallback", "succeeded", 0, coverage_status="missing_in_range")
    else:
        save_parquet(pd.DataFrame(columns=["article_id", "instrument_id", "symbols", "title", "summary", "url", "source_name", "vendor", "query_used", "query_type", "query_set_version", "relevance_score", "event_time", "known_time", "source", "fetched_at", "coverage_status"]), "news_articles", layer="normalized", mode="overwrite")
        log_crawl_job(str(uuid.uuid4()), "news_articles", "all", "succeeded", 0, coverage_status="missing")

    # Macro news empty schema
    macro_news_df = pd.DataFrame(columns=[
        "article_id", "query_topic", "title", "summary", "url", "source_name", "vendor",
        "query_used", "query_type", "query_set_version", "relevance_score",
        "event_time", "known_time", "source", "fetched_at", "coverage_status"
    ])
    save_parquet(macro_news_df, "macro_news_articles", layer="normalized", mode="overwrite")
    log_crawl_job(str(uuid.uuid4()), "macro_news_articles", "alpaca", "succeeded", 0, coverage_status="missing")

if __name__ == "__main__":
    tickers = ["AAPL", "AMZN", "GOOGL"]
    crawl_news(tickers)
