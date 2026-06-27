import argparse
import json
import logging
from pathlib import Path
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "memo_adaptation"

ACTION_MAP = {
    "Buy": 1.0,
    "Overweight": 0.5,
    "Hold": 0.0,
    "Underweight": -0.5,
    "Sell": -1.0
}

def load_jsonl(path: Path) -> dict:
    if not path.exists():
        return {}
    records = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                # Key rewards by reward_id; trajectories by trajectory_id; episodes by episode_id.
                record_id = record.get("reward_id") or record.get("trajectory_id") or record.get("episode_id")
                if record_id:
                    records[record_id] = record
    return records

def save_jsonl_append(path: Path, record: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

def parse_action(decision_text: str) -> str:
    """Extract action from decision text."""
    if not decision_text:
        return None

    # Heuristic parsing - adjust if needed based on actual LLM outputs
    text_lower = decision_text.lower().strip()

    if "overweight" in text_lower:
        return "Overweight"
    if "underweight" in text_lower:
        return "Underweight"
    if "buy" in text_lower:
        return "Buy"
    if "sell" in text_lower:
        return "Sell"
    if "hold" in text_lower:
        return "Hold"

    # If the decision text is exactly the action (like in mocks)
    for act in ACTION_MAP.keys():
        if decision_text.strip() == act:
            return act

    return None

def main():
    parser = argparse.ArgumentParser(description="Build rewards for a tournament.")
    parser.add_argument("--tournament-id", required=True)
    parser.add_argument("--reward-version", default="v0.1")
    parser.add_argument("--lambda-drawdown", type=float, default=0.5)
    args = parser.parse_args()

    trajectories_path = DATA_DIR / "trajectories" / "workflow_trajectories.jsonl"
    episodes_path = DATA_DIR / "episodes" / "trading_episodes.jsonl"
    rewards_path = DATA_DIR / "rewards" / "trajectory_rewards.jsonl"
    rewards_manifest = DATA_DIR / "rewards" / "manifest.json"

    if not trajectories_path.exists() or not episodes_path.exists():
        logger.error("Trajectories or episodes not found.")
        return

    trajectories = load_jsonl(trajectories_path)
    episodes = load_jsonl(episodes_path)

    existing_rewards = load_jsonl(rewards_path) if rewards_path.exists() else {}

    labels_path = BASE_DIR / "data" / "features" / "trading_labels"
    df_labels = None
    if labels_path.exists():
        logger.info(f"Loading labels from {labels_path}")
        df_labels = pd.read_parquet(labels_path)
    else:
        logger.error(f"Labels path not found: {labels_path}")

    def get_label_data(symbol: str, analysis_time: str, horizon_days: int):
        if df_labels is None or df_labels.empty:
            return None

        date_str = analysis_time[:10]
        # the horizon in the dataframe might be a string like '1d' or int like 1 or string '1'
        # let's be flexible
        match = df_labels[
            (df_labels["instrument_id"] == symbol) &
            (df_labels["analysis_date"].astype(str).str.startswith(date_str)) &
            (df_labels["horizon_days"].astype(str).str.replace("d", "") == str(horizon_days))
        ]

        if not match.empty:
            return match.iloc[0]
        return None

    rewards_added = 0

    for traj_id, traj in trajectories.items():
        if traj.get("tournament_id") != args.tournament_id:
            continue

        if traj.get("run_status") != "succeeded":
            continue

        ep = episodes.get(traj.get("episode_id"))
        if not ep:
            logger.warning(f"Episode {traj.get('episode_id')} not found for trajectory {traj_id}")
            continue

        final_decision = traj.get("agent_outputs", {}).get("final_trade_decision", "")
        action = parse_action(final_decision)
        exposure = ACTION_MAP.get(action)

        horizons = {"1d": 1, "5d": 5, "20d": 20}

        for horizon_key, horizon_days in horizons.items():
            reward_id = f"reward_{traj_id}_{horizon_key}"

            # Skip if already computed for this version
            if reward_id in existing_rewards and existing_rewards[reward_id].get("reward_version") == args.reward_version:
                continue

            ref_path = ep.get("label_refs", {}).get(horizon_key)

            reward_record = {
                "reward_id": reward_id,
                "trajectory_id": traj_id,
                "tournament_id": args.tournament_id,
                "generation_id": traj.get("generation_id"),
                "prompt_set_id": traj.get("prompt_set_id"),
                "episode_id": traj.get("episode_id"),
                "symbol": traj.get("symbol"),
                "horizon_days": horizon_days,
                "final_action": action,
                "future_return": None,
                "benchmark_return": None,
                "alpha_return": None,
                "max_drawdown_horizon": None,
                "directional_score": None,
                "alpha_score": None,
                "risk_penalty": None,
                "total_reward": None,
                "reward_version": args.reward_version,
                "created_at": pd.Timestamp.utcnow().isoformat()
            }

            if ref_path and exposure is not None:
                label_data = get_label_data(traj["symbol"], traj["analysis_time"], horizon_days)
                if label_data is not None:
                    alpha_ret = label_data.get("alpha_return", 0.0)
                    drawdown = label_data.get("max_drawdown_horizon", 0.0)

                    raw_pnl_score = exposure * alpha_ret
                    risk_penalty = abs(exposure) * max(0.0, -drawdown) # drawdown is typically negative, so -drawdown is positive loss
                    total_reward = raw_pnl_score - args.lambda_drawdown * risk_penalty

                    reward_record.update({
                        "future_return": float(label_data.get("future_return", 0.0)),
                        "benchmark_return": float(label_data.get("benchmark_return", 0.0)),
                        "alpha_return": float(alpha_ret),
                        "max_drawdown_horizon": float(drawdown),
                        "directional_score": (exposure > 0 and alpha_ret > 0) or (exposure < 0 and alpha_ret < 0),
                        "alpha_score": float(raw_pnl_score),
                        "risk_penalty": float(risk_penalty),
                        "total_reward": float(total_reward)
                    })

            save_jsonl_append(rewards_path, reward_record)
            existing_rewards[reward_id] = reward_record
            rewards_added += 1

    logger.info(f"Added {rewards_added} rewards for tournament {args.tournament_id}")

    # Update manifest
    manifest = {
        "dataset_version": args.reward_version,
        "count": len(existing_rewards),
        "generated_at": pd.Timestamp.utcnow().isoformat()
    }
    with open(rewards_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

if __name__ == "__main__":
    main()
