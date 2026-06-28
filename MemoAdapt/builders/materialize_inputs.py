import os
import sys
import json
import uuid
import pandas as pd
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import load_dataset, DATA_DIR
from core.audit import log_crawl_job

def load_all_datasets():
    print("Loading all datasets into memory...")
    datasets = {}
    try:
        datasets["price_daily"] = load_dataset("price_daily", layer="normalized")
    except FileNotFoundError:
        datasets["price_daily"] = pd.DataFrame()

    try:
        datasets["technical_indicators_daily"] = load_dataset("technical_indicators_daily", layer="features")
    except FileNotFoundError:
        datasets["technical_indicators_daily"] = pd.DataFrame()

    try:
        datasets["fundamentals_profile_snapshot"] = load_dataset("fundamentals_profile_snapshot", layer="normalized")
    except FileNotFoundError:
        datasets["fundamentals_profile_snapshot"] = pd.DataFrame()

    try:
        datasets["financial_statement_line_items"] = load_dataset("financial_statement_line_items", layer="normalized")
    except FileNotFoundError:
        datasets["financial_statement_line_items"] = pd.DataFrame()

    try:
        datasets["news_articles"] = load_dataset("news_articles", layer="normalized")
    except FileNotFoundError:
        datasets["news_articles"] = pd.DataFrame()

    try:
        datasets["macro_news_articles"] = load_dataset("macro_news_articles", layer="normalized")
    except FileNotFoundError:
        datasets["macro_news_articles"] = pd.DataFrame()

    try:
        datasets["social_sentiment_daily"] = load_dataset("social_sentiment_daily", layer="features")
    except FileNotFoundError:
        datasets["social_sentiment_daily"] = pd.DataFrame()

    try:
        datasets["macro_series_observations"] = load_dataset("macro_series_observations", layer="normalized")
    except FileNotFoundError:
        datasets["macro_series_observations"] = pd.DataFrame()

    # Pre-process time columns to avoid repeated conversion
    for name, df in datasets.items():
        if not df.empty and "known_time" in df.columns:
            df["known_time"] = pd.to_datetime(df["known_time"], utc=True)

    print("Datasets loaded.")
    return datasets

def materialize_inputs():
    print("Materializing Agent Inputs (Phase 1)...")

    snapshot_path = DATA_DIR / "snapshots" / "agent_input_snapshots" / "snapshots.jsonl"
    if not snapshot_path.exists():
        print("No snapshots.jsonl found. Run snapshot_builder first.")
        return

    datasets = load_all_datasets()

    out_dir = DATA_DIR / "memo_adaptation" / "materialized_inputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / "inputs.jsonl"

    # context policy ctx_default_v1 configs
    market_window_days = 90
    fundamentals_quarters = 8
    max_ticker_news = 20
    max_macro_news = 10
    max_social_items = 30

    count = 0
    with open(snapshot_path, "r", encoding="utf-8") as f_in, open(out_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip(): continue
            snapshot = json.loads(line)

            ticker = snapshot["instrument_id"]
            analysis_time_str = snapshot["analysis_time"]
            analysis_time = pd.to_datetime(analysis_time_str, utc=True)

            record = {
                "input_id": f"{ticker}_{analysis_time_str}_v0.1",
                "snapshot_id": f"{ticker}_{analysis_time_str.split('T')[0]}",
                "dataset_version": "v0.1",
                "symbol": ticker,
                "instrument_id": ticker,
                "analysis_date": analysis_time_str.split('T')[0],
                "analysis_time": analysis_time_str,
                "known_time_cutoff": analysis_time_str,
                "input_policy_id": "ctx_default_v1",
                "instrument_context": {},
                "latest_market_snapshot": {},
                "technical_snapshot": {},
                "fundamentals_snapshot": {},
                "market_window": [],
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
                "source_refs": {
                    "market_window_ref": snapshot.get("market_window_ref", ""),
                    "technical_snapshot_ref": snapshot.get("technical_snapshot_ref", ""),
                    "fundamentals_snapshot_ref": snapshot.get("fundamentals_snapshot_ref", ""),
                    "ticker_news_window_ref": snapshot.get("ticker_news_window_ref", ""),
                    "macro_news_window_ref": snapshot.get("macro_news_window_ref", ""),
                    "social_window_ref": snapshot.get("social_window_ref", ""),
                    "macro_snapshot_ref": snapshot.get("macro_snapshot_ref", "")
                },
                "created_at": pd.Timestamp.utcnow().isoformat()
            }

            # Helper to filter
            def get_window(df_name, is_instrument=True, n=None):
                df = datasets.get(df_name)
                if df is None or df.empty: return pd.DataFrame()

                mask = (df["known_time"] <= analysis_time)
                if is_instrument and "instrument_id" in df.columns:
                    mask = mask & (df["instrument_id"] == ticker)

                filtered = df[mask].copy()
                # Sort by known_time ascending
                if "known_time" in filtered.columns:
                    filtered = filtered.sort_values("known_time")

                if n is not None:
                    filtered = filtered.tail(n)
                return filtered

            # Helper to stringify date cols safely
            def stringify_dates(df_in):
                df_out = df_in.copy()
                for col in ["trade_date", "event_time", "known_time", "fetched_at", "observation_date", "date"]:
                    if col in df_out.columns:
                        df_out[col] = df_out[col].astype(str)
                return df_out

            # Market Window
            df_mkt = get_window("price_daily", n=market_window_days)
            if not df_mkt.empty:
                df_mkt_json = stringify_dates(df_mkt)
                record["market_window"] = df_mkt_json.to_dict(orient="records")
                record["latest_market_snapshot"] = record["market_window"][-1]
            else:
                record["coverage"]["market"] = "missing"

            # Technical Snapshot
            df_tech = get_window("technical_indicators_daily", n=1)
            if not df_tech.empty:
                df_tech_json = stringify_dates(df_tech)
                record["technical_snapshot"] = df_tech_json.to_dict(orient="records")[0]
            else:
                record["coverage"]["technical"] = "missing"

            # Fundamentals
            df_prof = get_window("fundamentals_profile_snapshot", n=1)
            if not df_prof.empty:
                df_prof_json = stringify_dates(df_prof)
                record["fundamentals_snapshot"] = df_prof_json.to_dict(orient="records")[0]
                record["coverage"]["fundamentals"] = "partial" # as per current implementation

            df_fin = get_window("financial_statement_line_items", n=fundamentals_quarters * 10) # 8 quarters * approx 10 items
            if not df_fin.empty:
                df_fin_json = stringify_dates(df_fin)
                record["financial_statement_window"] = df_fin_json.to_dict(orient="records")

            # News
            df_news = get_window("news_articles", n=max_ticker_news)
            if not df_news.empty:
                df_news_json = stringify_dates(df_news)
                record["ticker_news_window"] = df_news_json.to_dict(orient="records")
                record["coverage"]["ticker_news"] = "ok" if len(df_news) > 0 else "missing"

            df_macro_news = get_window("macro_news_articles", is_instrument=False, n=max_macro_news)
            if not df_macro_news.empty:
                df_macro_news_json = stringify_dates(df_macro_news)
                record["macro_news_window"] = df_macro_news_json.to_dict(orient="records")
                record["coverage"]["macro_news"] = "ok" if len(df_macro_news) > 0 else "missing"

            # Social
            df_soc = get_window("social_sentiment_daily", n=max_social_items)
            if not df_soc.empty:
                df_soc_json = stringify_dates(df_soc)
                record["social_window"] = df_soc_json.to_dict(orient="records")
                record["coverage"]["social"] = "ok" if len(df_soc) > 0 else "missing"

            # Macro
            df_macro = get_window("macro_series_observations", is_instrument=False)
            if not df_macro.empty:
                # get latest per series
                latest_macro = df_macro.groupby("series_id").last().reset_index()
                latest_macro_json = stringify_dates(latest_macro)
                # Convert to dict where key is series_id
                macro_dict = {row["series_id"]: row for row in latest_macro_json.to_dict(orient="records")}
                record["macro_snapshot"] = macro_dict
                record["coverage"]["macro"] = "ok" if len(macro_dict) > 0 else "missing"

            f_out.write(json.dumps(record, default=str) + "\n")
            count += 1

    # Also save as parquet
    if count > 0:
        # Saving jsonl is main artifact, parquet for metadata summary
        df_inputs = pd.read_json(out_file, lines=True)
        # Drop complex types for parquet metadata
        df_parquet = df_inputs.drop(columns=["instrument_context", "latest_market_snapshot", "technical_snapshot", "fundamentals_snapshot", "market_window", "financial_statement_window", "ticker_news_window", "macro_news_window", "social_window", "macro_snapshot", "coverage", "source_refs"])
        df_parquet.to_parquet(out_dir / "inputs.parquet", engine="pyarrow")

        manifest = {
            "dataset_version": "v0.1",
            "count": count,
            "generated_at": pd.Timestamp.utcnow().isoformat()
        }
        with open(out_dir / "manifest.json", "w") as mf:
            json.dump(manifest, mf, indent=2)

    print(f"Materialized {count} inputs.")

if __name__ == "__main__":
    materialize_inputs()
