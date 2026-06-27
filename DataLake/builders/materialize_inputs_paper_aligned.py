import os
import sys
import json
import argparse
import pandas as pd
from pathlib import Path

# Adjust paths to import local core helpers
DATALAKE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = DATALAKE_DIR.parent
sys.path.append(str(DATALAKE_DIR))

# Use core.storage load_dataset
try:
    from core.storage import load_dataset, DATA_DIR
except ImportError:
    # fallback
    DATA_DIR = DATALAKE_DIR / "data"
    def load_dataset(name, layer):
        path = DATA_DIR / layer / name
        if not path.exists():
            raise FileNotFoundError
        return pd.read_parquet(path)

def load_all_datasets():
    print("Loading all datasets into memory...")
    datasets = {}

    def try_load(name, layer):
        try:
            return load_dataset(name, layer=layer)
        except FileNotFoundError:
            return pd.DataFrame()

    datasets["price_daily"] = try_load("price_daily", "normalized")
    datasets["technical_indicators_daily"] = try_load("technical_indicators_daily", "features")
    datasets["fundamentals_profile_snapshot"] = try_load("fundamentals_profile_snapshot", "normalized")
    datasets["financial_statement_line_items"] = try_load("financial_statement_line_items", "normalized")
    datasets["news_articles"] = try_load("news_articles", "normalized")
    datasets["macro_news_articles"] = try_load("macro_news_articles", "normalized")
    datasets["social_sentiment_daily"] = try_load("social_sentiment_daily", "features")
    datasets["macro_series_observations"] = try_load("macro_series_observations", "normalized")

    # Pre-process time columns to avoid repeated conversion
    for name, df in datasets.items():
        if not df.empty and "known_time" in df.columns:
            df["known_time"] = pd.to_datetime(df["known_time"], utc=True)

    print("Datasets loaded.")
    return datasets

def rank_and_dedup_news(df, max_items, is_macro=False, ticker=None):
    if df.empty:
        return df

    # 1. remove duplicates by url if present
    if "url" in df.columns and "canonical_url" in df.columns:
        df["dedup_url"] = df["canonical_url"].fillna(df["url"])
        df = df.drop_duplicates(subset=["dedup_url"], keep="last")
    elif "url" in df.columns:
        df = df.drop_duplicates(subset=["url"], keep="last")

    # 2. remove near-duplicates by normalized title
    if "title" in df.columns:
        df["norm_title"] = df["title"].str.lower().str.replace(r'[^a-z0-9 ]', '', regex=True)
        df = df.drop_duplicates(subset=["norm_title"], keep="last")

    # Scoring
    scores = pd.Series(0, index=df.index)

    # 3. prioritize direct ticker match
    if not is_macro and ticker and "title" in df.columns:
        scores += df["title"].str.contains(ticker, case=False).astype(int) * 10

    # 4. prioritize higher relevance_score if present
    if "relevance_score" in df.columns:
        scores += pd.to_numeric(df["relevance_score"], errors="coerce").fillna(0) * 5

    # 5. prioritize material event keywords
    if "title" in df.columns:
        keywords = "earnings|guidance|revenue|eps|margin|antitrust|lawsuit|acquisition|merger|buyback|layoff|product launch|regulation|fed|inflation|interest rate|supply chain|cloud|advertising|iphone|aws|youtube"
        scores += df["title"].str.contains(keywords, case=False).astype(int) * 8

    df["rank_score"] = scores

    # 6. preserve date diversity by sorting by rank_score then recency
    df = df.sort_values(by=["rank_score", "known_time"], ascending=[False, False])

    # Truncate
    df = df.head(max_items)
    # Sort back chronologically for output
    df = df.sort_values(by="known_time", ascending=True)
    return df.drop(columns=["dedup_url", "norm_title", "rank_score"], errors="ignore")

def rank_social(df, max_items):
    if df.empty:
        return df

    scores = pd.Series(0, index=df.index)
    if "score" in df.columns:
        scores += pd.to_numeric(df["score"], errors="coerce").fillna(0)
    if "relevance_score" in df.columns:
        scores += pd.to_numeric(df["relevance_score"], errors="coerce").fillna(0) * 10

    df["rank_score"] = scores
    df = df.sort_values(by=["rank_score", "known_time"], ascending=[False, False]).head(max_items)
    df = df.sort_values(by="known_time", ascending=True)
    return df.drop(columns=["rank_score"], errors="ignore")

def materialize_inputs(args):
    print(f"Materializing Agent Inputs for {args.context_policy_id}...")

    # Load policy config
    policy_path = DATA_DIR / "memo_adaptation" / "context_policies" / "context_policies.json"
    with open(policy_path, "r") as f:
        raw_policies = json.load(f)

    if isinstance(raw_policies, list):
        policies = {
            policy["context_policy_id"]: policy
            for policy in raw_policies
            if "context_policy_id" in policy
        }
    else:
        policies = raw_policies

    if args.context_policy_id not in policies:
        print(f"Policy {args.context_policy_id} not found in {policy_path}")
        return

    policy = policies[args.context_policy_id]

    snapshot_path = DATA_DIR / "snapshots" / "agent_input_snapshots" / "snapshots.jsonl"
    if not snapshot_path.exists():
        print("No snapshots.jsonl found. Run snapshot_builder first.")
        return

    datasets = load_all_datasets()

    out_dir = DATA_DIR / "memo_adaptation" / "materialized_inputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / f"inputs_{args.context_policy_id}.jsonl"

    count = 0
    with open(snapshot_path, "r", encoding="utf-8") as f_in, open(out_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip(): continue
            snapshot = json.loads(line)

            ticker = snapshot["instrument_id"]
            analysis_time_str = snapshot["analysis_time"]
            analysis_time = pd.to_datetime(analysis_time_str, utc=True)

            record = {
                "input_id": f"{ticker}_{analysis_time_str}_{args.context_policy_id}",
                "snapshot_id": f"{ticker}_{analysis_time_str.split('T')[0]}",
                "dataset_version": "v0.1",
                "symbol": ticker,
                "instrument_id": ticker,
                "analysis_date": analysis_time_str.split('T')[0],
                "analysis_time": analysis_time_str,
                "known_time_cutoff": analysis_time_str,
                "input_policy_id": args.context_policy_id,
                "context_policy_version": "v1",
                "context_windows": {
                    "market_window_trading_rows": policy["market_window_trading_rows"],
                    "technical_window_trading_rows": policy["technical_window_trading_rows"],
                    "ticker_news_window_days": policy["ticker_news_window_days"],
                    "ticker_news_max_materialized": policy["ticker_news_max_materialized"],
                    "macro_news_window_days": policy["macro_news_window_days"],
                    "macro_news_max_materialized": policy["macro_news_max_materialized"],
                    "social_window_days": policy["social_window_days"],
                    "social_max_materialized": policy["social_max_materialized"],
                    "sentiment_window_days": policy["sentiment_window_days"],
                    "sentiment_max_materialized": policy["sentiment_max_materialized"],
                    "financial_statement_quarters": policy["financial_statement_quarters"]
                },
                "instrument_context": {},
                "latest_market_snapshot": {},
                "technical_snapshot": {},
                "fundamentals_snapshot": {},
                "market_window": [],
                "technical_window": [],
                "financial_statement_window": [],
                "ticker_news_window": [],
                "macro_news_window": [],
                "social_window": [],
                "macro_snapshot": {},
                "coverage": {
                    "market": "ok",
                    "technical": "ok",
                    "fundamentals": "missing",
                    "ticker_news": "missing",
                    "macro_news": "missing",
                    "social": "missing",
                    "macro": "missing"
                },
                "created_at": pd.Timestamp.utcnow().isoformat()
            }

            # Helper to filter by known_time <= analysis_time
            def get_window(df_name, is_instrument=True, days_lookback=None, trading_rows=None):
                df = datasets.get(df_name)
                if df is None or df.empty: return pd.DataFrame()

                mask = (df["known_time"] <= analysis_time)
                if days_lookback is not None:
                    cutoff = analysis_time - pd.Timedelta(days=days_lookback)
                    mask = mask & (df["known_time"] >= cutoff)

                if is_instrument and "instrument_id" in df.columns:
                    mask = mask & (df["instrument_id"] == ticker)

                filtered = df[mask].copy()
                if "known_time" in filtered.columns:
                    filtered = filtered.sort_values("known_time")

                if trading_rows is not None:
                    filtered = filtered.tail(trading_rows)
                return filtered

            # Helper to stringify date cols
            def stringify_dates(df_in):
                df_out = df_in.copy()
                for col in ["trade_date", "event_time", "known_time", "fetched_at", "observation_date", "date"]:
                    if col in df_out.columns:
                        df_out[col] = df_out[col].astype(str)
                return df_out

            # Market Window
            df_mkt = get_window("price_daily", trading_rows=policy["market_window_trading_rows"])
            if not df_mkt.empty:
                record["market_window"] = stringify_dates(df_mkt).to_dict(orient="records")
                record["latest_market_snapshot"] = record["market_window"][-1]
            else:
                record["coverage"]["market"] = "missing"

            # Technical Window
            df_tech = get_window("technical_indicators_daily", trading_rows=policy["technical_window_trading_rows"])
            if not df_tech.empty:
                record["technical_window"] = stringify_dates(df_tech).to_dict(orient="records")
                record["technical_snapshot"] = record["technical_window"][-1]
            else:
                record["coverage"]["technical"] = "missing"

            # Fundamentals
            df_prof = get_window("fundamentals_profile_snapshot", trading_rows=1)
            if not df_prof.empty:
                record["fundamentals_snapshot"] = stringify_dates(df_prof).to_dict(orient="records")[0]
                record["coverage"]["fundamentals"] = "partial"

            df_fin = get_window("financial_statement_line_items", trading_rows=policy["financial_statement_quarters"] * 20) # 8 quarters * ~20 items
            if not df_fin.empty:
                record["financial_statement_window"] = stringify_dates(df_fin).to_dict(orient="records")

            # News
            df_news = get_window("news_articles", days_lookback=policy["ticker_news_window_days"])
            df_news = rank_and_dedup_news(df_news, policy["ticker_news_max_materialized"], is_macro=False, ticker=ticker)
            if not df_news.empty:
                record["ticker_news_window"] = stringify_dates(df_news).to_dict(orient="records")
                record["coverage"]["ticker_news"] = "ok"

            df_macro_news = get_window("macro_news_articles", is_instrument=False, days_lookback=policy["macro_news_window_days"])
            df_macro_news = rank_and_dedup_news(df_macro_news, policy["macro_news_max_materialized"], is_macro=True)
            if not df_macro_news.empty:
                record["macro_news_window"] = stringify_dates(df_macro_news).to_dict(orient="records")
                record["coverage"]["macro_news"] = "ok"

            # Social
            df_soc = get_window("social_sentiment_daily", days_lookback=policy["social_window_days"])
            df_soc = rank_social(df_soc, policy["social_max_materialized"])
            if not df_soc.empty:
                record["social_window"] = stringify_dates(df_soc).to_dict(orient="records")
                record["coverage"]["social"] = "ok"

            # Macro
            df_macro = get_window("macro_series_observations", is_instrument=False)
            if not df_macro.empty:
                latest_macro = df_macro.groupby("series_id", observed=True).last().reset_index()
                macro_dict = {row["series_id"]: row for row in stringify_dates(latest_macro).to_dict(orient="records")}
                record["macro_snapshot"] = macro_dict
                record["coverage"]["macro"] = "ok" if len(macro_dict) > 0 else "missing"

            f_out.write(json.dumps(record, default=str) + "\n")
            count += 1

    # Also save as parquet
    if count > 0:
        df_inputs = pd.read_json(out_file, lines=True)
        cols_to_drop = ["instrument_context", "latest_market_snapshot", "technical_snapshot", "fundamentals_snapshot", "market_window", "technical_window", "financial_statement_window", "ticker_news_window", "macro_news_window", "social_window", "macro_snapshot", "coverage", "context_windows"]
        existing_cols_to_drop = [c for c in cols_to_drop if c in df_inputs.columns]
        df_parquet = df_inputs.drop(columns=existing_cols_to_drop)
        df_parquet.to_parquet(out_dir / f"inputs_{args.context_policy_id}.parquet", engine="pyarrow")

    print(f"Materialized {count} inputs for {args.context_policy_id}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-policy-id", default="ctx_paper_aligned_v1")
    args = parser.parse_args()
    materialize_inputs(args)
