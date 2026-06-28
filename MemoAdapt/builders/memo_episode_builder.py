import os
import sys
import json
import pandas as pd
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import DATA_DIR

def build_episodes():
    print("Building Trading Episodes (Phase 2)...")

    snapshot_path = DATA_DIR / "snapshots" / "agent_input_snapshots" / "snapshots.jsonl"
    if not snapshot_path.exists():
        print("No snapshots.jsonl found.")
        return

    # Load trading_labels to filter out episodes without all required labels
    labels_path = DATA_DIR / "features" / "trading_labels"
    valid_keys = set()
    if labels_path.exists():
        try:
            df_labels = pd.read_parquet(labels_path, engine="pyarrow")
            # Create a set of (instrument_id, analysis_date) that have all 3 horizons
            # horizon_days is stored as string/int like "1", "5", "20"
            df_labels["horizon_days"] = df_labels["horizon_days"].astype(str).str.replace("d", "")
            grouped = df_labels.groupby(["instrument_id", "analysis_date"])["horizon_days"].apply(set)
            for (inst, date), horizons in grouped.items():
                date_str = str(date)[:10]
                if {"1", "5", "20"}.issubset(horizons):
                    valid_keys.add((str(inst), date_str))
        except Exception as e:
            print(f"Error loading labels: {e}")

    out_dir = DATA_DIR / "memo_adaptation" / "episodes"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / "trading_episodes.jsonl"

    count = 0
    with open(snapshot_path, "r", encoding="utf-8") as f_in, open(out_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip(): continue
            snapshot = json.loads(line)

            ticker = snapshot["instrument_id"]
            analysis_time_str = snapshot["analysis_time"]
            analysis_date = analysis_time_str.split('T')[0]

            # Skip if we don't have all labels
            if valid_keys and (ticker, analysis_date) not in valid_keys:
                continue

            record = {
                "episode_id": f"{ticker}_{analysis_date}",
                "symbol": ticker,
                "instrument_id": ticker,
                "analysis_date": analysis_date,
                "analysis_time": analysis_time_str,
                "known_time_cutoff": analysis_time_str,
                "input_id": f"{ticker}_{analysis_time_str}_v0.1",
                "input_path": "MemoAdapt/data/memo_adaptation/materialized_inputs/inputs.jsonl",

                "target_workflow": "tradingagents",
                "target_agents": [
                    "market_analyst",
                    "sentiment_analyst",
                    "news_analyst",
                    "fundamentals_analyst",
                    "bull_researcher",
                    "bear_researcher",
                    "research_manager",
                    "trader",
                    "risk_team",
                    "portfolio_manager"
                ],

                "label_refs": {
                    "1d": f"trading_labels?instrument_id={ticker}&analysis_date={analysis_date}&horizon_days=1d",
                    "5d": f"trading_labels?instrument_id={ticker}&analysis_date={analysis_date}&horizon_days=5d",
                    "20d": f"trading_labels?instrument_id={ticker}&analysis_date={analysis_date}&horizon_days=20d"
                },

                "coverage": {},
                "episode_version": "v0.1",
                "created_at": pd.Timestamp.utcnow().isoformat()
            }

            f_out.write(json.dumps(record) + "\n")
            count += 1

    if count > 0:
        manifest = {
            "dataset_version": "v0.1",
            "count": count,
            "generated_at": pd.Timestamp.utcnow().isoformat()
        }
        with open(out_dir / "manifest.json", "w") as mf:
            json.dump(manifest, mf, indent=2)

    print(f"Generated {count} episodes.")

if __name__ == "__main__":
    build_episodes()
