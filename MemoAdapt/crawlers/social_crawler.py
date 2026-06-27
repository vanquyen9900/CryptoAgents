import argparse
import os
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.audit import log_crawl_job
from core.storage import save_parquet, save_raw_json


try:
    from dotenv import load_dotenv

    PROJECT_DIR = Path(__file__).resolve().parents[2]
    load_dotenv(PROJECT_DIR / "TradingAgents" / ".env", override=False)
except Exception:
    pass

ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY")
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

RETAIL_SENTIMENT_KEYWORDS = [
    "retail",
    "investor sentiment",
    "traders",
    "trading",
    "options",
    "calls",
    "puts",
    "short squeeze",
    "meme stock",
    "wallstreetbets",
    "reddit",
    "stocktwits",
    "social media",
    "bullish",
    "bearish",
    "buy the dip",
    "selloff",
    "momentum",
    "hype",
    "earnings reaction",
    "guidance reaction",
]


def format_av_time(value: str, end_of_day: bool = False) -> str:
    dt = datetime.strptime(value, "%Y-%m-%d")
    if end_of_day:
        return dt.strftime("%Y%m%dT2359")
    return dt.strftime("%Y%m%dT0000")


def date_windows(start_date: str, end_date: str, window_days: int = 92):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=window_days - 1), end)
        yield current.strftime("%Y-%m-%d"), window_end.strftime("%Y-%m-%d")
        current = window_end + timedelta(days=1)


def parse_av_published_time(raw: str):
    if not raw:
        return None
    try:
        return pd.to_datetime(datetime.strptime(raw, "%Y%m%dT%H%M"), utc=True)
    except ValueError:
        return pd.to_datetime(raw, utc=True, errors="coerce")


def text_keyword_score(text: str) -> int:
    low = (text or "").lower()
    return sum(1 for keyword in RETAIL_SENTIMENT_KEYWORDS if keyword in low)


def label_to_counts(label: str):
    normalized = (label or "").lower()
    if "bearish" in normalized:
        return 0, 1, 0
    if "bullish" in normalized:
        return 1, 0, 0
    return 0, 0, 1


def empty_reddit_posts():
    return pd.DataFrame(columns=[
        "post_id",
        "instrument_id",
        "subreddit",
        "title",
        "selftext",
        "url",
        "score",
        "num_comments",
        "event_time",
        "known_time",
        "source",
        "fetched_at",
        "coverage_status",
    ])


def empty_stocktwits_messages():
    return pd.DataFrame(columns=[
        "message_id",
        "instrument_id",
        "body",
        "user",
        "sentiment",
        "event_time",
        "known_time",
        "source",
        "fetched_at",
        "coverage_status",
    ])


def empty_social_sentiment():
    return pd.DataFrame(columns=[
        "instrument_id",
        "date",
        "event_time",
        "known_time",
        "article_count",
        "stocktwits_message_count",
        "reddit_post_count",
        "retail_keyword_count",
        "bullish_count",
        "bearish_count",
        "neutral_count",
        "sentiment_score",
        "social_proxy_score",
        "relevance_score",
        "score",
        "sentiment",
        "title",
        "summary",
        "source",
        "fetched_at",
        "coverage_status",
    ])


def fetch_alpha_vantage_news_sentiment(ticker: str, start_date: str, end_date: str, limit: int = 1000):
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "time_from": format_av_time(start_date),
        "time_to": format_av_time(end_date, end_of_day=True),
        "sort": "EARLIEST",
        "limit": str(limit),
        "apikey": ALPHA_VANTAGE_KEY,
    }
    response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    notice = data.get("Information") or data.get("Note")
    if notice:
        raise RuntimeError(notice)
    return data


def normalize_articles(ticker: str, payload: dict):
    records = []
    for item in payload.get("feed", []) or []:
        published = parse_av_published_time(item.get("time_published"))
        if published is None or pd.isna(published):
            continue

        ticker_sentiment = {}
        for ts in item.get("ticker_sentiment", []) or []:
            if str(ts.get("ticker", "")).upper() == ticker.upper():
                ticker_sentiment = ts
                break

        title = item.get("title", "") or ""
        summary = item.get("summary", "") or ""
        keyword_count = text_keyword_score(f"{title} {summary}")
        relevance = float(ticker_sentiment.get("relevance_score") or 0.0)
        ticker_score = float(ticker_sentiment.get("ticker_sentiment_score") or 0.0)
        ticker_label = ticker_sentiment.get("ticker_sentiment_label") or item.get("overall_sentiment_label") or "Neutral"
        overall_score = float(item.get("overall_sentiment_score") or 0.0)

        # Keep every article, but weight retail/social-like language higher.
        social_proxy_score = relevance + min(keyword_count, 5) * 0.2 + abs(ticker_score) * 0.5
        bullish, bearish, neutral = label_to_counts(ticker_label)

        records.append({
            "article_id": str(uuid.uuid5(uuid.NAMESPACE_URL, item.get("url", "") or f"{ticker}-{title}-{published}")),
            "instrument_id": ticker.upper(),
            "title": title,
            "summary": summary,
            "url": item.get("url", ""),
            "source_name": item.get("source", "Alpha Vantage"),
            "vendor": "alpha_vantage",
            "event_time": published,
            "known_time": published,
            "date": published.strftime("%Y-%m-%d"),
            "relevance_score": relevance,
            "ticker_sentiment_score": ticker_score,
            "ticker_sentiment_label": ticker_label,
            "overall_sentiment_score": overall_score,
            "overall_sentiment_label": item.get("overall_sentiment_label", ""),
            "retail_keyword_count": keyword_count,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "social_proxy_score": social_proxy_score,
            "source": "alpha_vantage_news_sentiment_proxy",
            "fetched_at": pd.Timestamp.utcnow(),
            "coverage_status": "proxy",
        })
    return records


def aggregate_daily_proxy(article_df: pd.DataFrame) -> pd.DataFrame:
    if article_df.empty:
        return empty_social_sentiment()

    rows = []
    article_df = article_df.sort_values(["instrument_id", "known_time", "social_proxy_score"])
    for (ticker, date), group in article_df.groupby(["instrument_id", "date"], observed=True):
        weighted = group["ticker_sentiment_score"] * group["relevance_score"].clip(lower=0.01)
        weight_sum = group["relevance_score"].clip(lower=0.01).sum()
        sentiment_score = float(weighted.sum() / weight_sum) if weight_sum else float(group["ticker_sentiment_score"].mean())
        top = group.sort_values(["social_proxy_score", "known_time"], ascending=[False, False]).head(5)
        latest = group.sort_values("known_time").iloc[-1]
        top_titles = " | ".join(top["title"].astype(str).tolist())
        rows.append({
            "instrument_id": ticker,
            "date": date,
            "event_time": pd.to_datetime(date, utc=True),
            "known_time": latest["known_time"],
            "article_count": int(len(group)),
            "stocktwits_message_count": 0,
            "reddit_post_count": 0,
            "retail_keyword_count": int(group["retail_keyword_count"].sum()),
            "bullish_count": int(group["bullish_count"].sum()),
            "bearish_count": int(group["bearish_count"].sum()),
            "neutral_count": int(group["neutral_count"].sum()),
            "sentiment_score": sentiment_score,
            "social_proxy_score": float(group["social_proxy_score"].mean()),
            "relevance_score": float(group["relevance_score"].mean()),
            "score": float(group["social_proxy_score"].mean()),
            "sentiment": "Bullish" if sentiment_score > 0.15 else "Bearish" if sentiment_score < -0.15 else "Neutral",
            "title": top_titles,
            "summary": (
                f"Alpha Vantage news-sentiment proxy: {len(group)} articles; "
                f"bullish={int(group['bullish_count'].sum())}, "
                f"bearish={int(group['bearish_count'].sum())}, "
                f"retail_keyword_hits={int(group['retail_keyword_count'].sum())}."
            ),
            "source": "alpha_vantage_news_sentiment_proxy",
            "fetched_at": pd.Timestamp.utcnow(),
            "coverage_status": "proxy",
        })
    return pd.DataFrame(rows)


def crawl_social(
    tickers=None,
    start_date="2021-01-01",
    end_date="2022-12-31",
    known_time_cutoff=None,
    request_sleep_seconds=12.5,
    window_days=92,
):
    print("Crawling Social Data (Phase F)...")
    tickers = tickers or ["AAPL", "AMZN", "GOOGL"]

    save_parquet(empty_reddit_posts(), "reddit_posts", layer="normalized", mode="overwrite")
    log_crawl_job(str(uuid.uuid4()), "reddit_posts", "reddit_rss", "succeeded", 0, coverage_status="missing")

    save_parquet(empty_stocktwits_messages(), "stocktwits_messages", layer="normalized", mode="overwrite")
    log_crawl_job(str(uuid.uuid4()), "stocktwits_messages", "stocktwits_api", "succeeded", 0, coverage_status="missing")

    if not ALPHA_VANTAGE_KEY:
        print("ALPHA_VANTAGE_API_KEY not found. Writing empty social sentiment proxy.")
        save_parquet(empty_social_sentiment(), "social_sentiment_daily", layer="features", mode="overwrite")
        log_crawl_job(str(uuid.uuid4()), "social_sentiment_daily", "alpha_vantage", "failed", 0, "Missing API Key", coverage_status="missing")
        return

    all_articles = []
    errors = []
    for ticker in tickers:
        for window_start, window_end in date_windows(start_date, end_date, window_days=window_days):
            print(f"Alpha Vantage NEWS_SENTIMENT proxy: {ticker} {window_start} to {window_end}")
            try:
                payload = fetch_alpha_vantage_news_sentiment(ticker, window_start, window_end)
                save_raw_json(payload, "social_proxy_articles/source=alpha_vantage", f"{ticker}_{window_start}_{window_end}.json")
                all_articles.extend(normalize_articles(ticker, payload))
            except Exception as exc:
                message = f"{ticker} {window_start}-{window_end}: {exc}"
                print(f"Warning: {message}")
                errors.append(message)
            time.sleep(request_sleep_seconds)

    article_df = pd.DataFrame(all_articles)
    if not article_df.empty:
        cutoff_value = known_time_cutoff or f"{end_date} 23:59:59"
        cutoff = pd.Timestamp(cutoff_value, tz="UTC")
        article_df = article_df[article_df["known_time"] <= cutoff]
        article_df = article_df.drop_duplicates(subset=["url", "instrument_id"])

    if article_df.empty:
        daily_df = empty_social_sentiment()
        coverage = "missing"
    else:
        daily_df = aggregate_daily_proxy(article_df)
        coverage = "proxy"
        save_parquet(article_df, "social_proxy_articles", layer="normalized", partition_cols=["instrument_id"], mode="overwrite")

    save_parquet(daily_df, "social_sentiment_daily", layer="features", partition_cols=["instrument_id"] if not daily_df.empty else None, mode="overwrite")
    status = "partial" if errors else "succeeded"
    log_crawl_job(
        str(uuid.uuid4()),
        "social_sentiment_daily",
        "alpha_vantage_news_sentiment_proxy",
        status,
        len(daily_df),
        records_read=len(article_df),
        error="\n".join(errors[:20]),
        error_count=len(errors),
        coverage_status=coverage,
    )
    print(f"Saved {len(daily_df)} daily social sentiment proxy rows from {len(article_df)} articles.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+", default=["AAPL", "AMZN", "GOOGL"])
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default="2022-12-31")
    parser.add_argument("--known-time-cutoff", default=None)
    parser.add_argument("--request-sleep-seconds", type=float, default=12.5)
    parser.add_argument("--window-days", type=int, default=92)
    args = parser.parse_args()
    crawl_social(
        tickers=args.tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        known_time_cutoff=args.known_time_cutoff,
        request_sleep_seconds=args.request_sleep_seconds,
        window_days=args.window_days,
    )
