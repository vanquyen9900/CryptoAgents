import argparse
import json
import logging
from pathlib import Path
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "memo_adaptation"

def load_jsonl(path: Path) -> dict:
    if not path.exists():
        return {}
    records = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                # Key by appropriate ID
                record_id = record.get("score_id") or record.get("reward_id") or record.get("trajectory_id") or record.get("prompt_set_id")
                if record_id:
                    records[record_id] = record
    return records

def save_jsonl_append(path: Path, record: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

def comparison_group_for(row: dict) -> str:
    explicit = row.get("comparison_group")
    if explicit:
        return str(explicit)
    return "baseline_no_memory" if row.get("memory_policy_id") == "mem_none_v1" else "memory_enabled"

def memory_bank_version_for(row: dict) -> str:
    explicit = row.get("memory_bank_version")
    if explicit:
        return str(explicit)
    return "none" if row.get("memory_policy_id") == "mem_none_v1" else "unknown"

def main():
    parser = argparse.ArgumentParser(description="Score tournament prompt sets.")
    parser.add_argument("--tournament-id", required=True)
    parser.add_argument("--score-version", default="v0.1")
    parser.add_argument("--data-mode", default=None)
    parser.add_argument("--comparison-group", default=None)
    parser.add_argument("--memory-bank-version", default=None)
    parser.add_argument(
        "--score-scope-id",
        default=None,
        help="Optional suffix to create independent score rows for a filtered subset.",
    )
    args = parser.parse_args()

    trajectories_path = DATA_DIR / "trajectories" / "workflow_trajectories.jsonl"
    rewards_path = DATA_DIR / "rewards" / "trajectory_rewards.jsonl"
    scores_path = DATA_DIR / "tournament_scores" / "tournament_scores.jsonl"
    scores_manifest = DATA_DIR / "tournament_scores" / "manifest.json"

    if not trajectories_path.exists() or not rewards_path.exists():
        logger.error("Trajectories or rewards not found.")
        return

    trajectories = load_jsonl(trajectories_path)
    rewards = load_jsonl(rewards_path)

    existing_scores = load_jsonl(scores_path) if scores_path.exists() else {}

    def keep_trajectory(traj: dict) -> bool:
        if traj.get("tournament_id") != args.tournament_id:
            return False
        if args.data_mode and traj.get("data_mode") != args.data_mode:
            return False
        if args.comparison_group and comparison_group_for(traj) != args.comparison_group:
            return False
        if args.memory_bank_version and memory_bank_version_for(traj) != args.memory_bank_version:
            return False
        return True

    selected_trajectory_ids = {
        traj_id
        for traj_id, traj in trajectories.items()
        if keep_trajectory(traj)
    }
    logger.info(
        "Selected %d trajectories for scoring filters: data_mode=%s comparison_group=%s memory_bank_version=%s",
        len(selected_trajectory_ids),
        args.data_mode,
        args.comparison_group,
        args.memory_bank_version,
    )

    # Group trajectories by prompt set
    ps_runs = {}
    ps_rewards = {}

    for traj_id, traj in trajectories.items():
        if traj_id not in selected_trajectory_ids:
            continue

        ps_id = traj.get("prompt_set_id")
        if ps_id not in ps_runs:
            ps_runs[ps_id] = {"succeeded": 0, "failed": 0, "generation_id": traj.get("generation_id")}
            ps_rewards[ps_id] = {"1d": [], "5d": [], "20d": []}

        if traj.get("run_status") == "succeeded":
            ps_runs[ps_id]["succeeded"] += 1
        else:
            ps_runs[ps_id]["failed"] += 1

    for reward_id, reward in rewards.items():
        if reward.get("tournament_id") != args.tournament_id:
            continue
        if reward.get("trajectory_id") not in selected_trajectory_ids:
            continue

        ps_id = reward.get("prompt_set_id")
        horizon = f"{reward.get('horizon_days')}d"

        if ps_id in ps_rewards and horizon in ps_rewards[ps_id]:
            total_reward = reward.get("total_reward")
            if total_reward is not None:
                ps_rewards[ps_id][horizon].append(total_reward)

    scores_added = 0
    scores_list = []

    for ps_id, runs_info in ps_runs.items():
        scope_part = f"_{args.score_scope_id}" if args.score_scope_id else ""
        score_id = f"score_{args.tournament_id}{scope_part}_{ps_id}"

        if score_id in existing_scores and existing_scores[score_id].get("score_version") == args.score_version:
            continue

        rewards_1d = ps_rewards[ps_id]["1d"]
        rewards_5d = ps_rewards[ps_id]["5d"]
        rewards_20d = ps_rewards[ps_id]["20d"]

        mean_1d = np.mean(rewards_1d) if rewards_1d else 0.0
        mean_5d = np.mean(rewards_5d) if rewards_5d else 0.0
        mean_20d = np.mean(rewards_20d) if rewards_20d else 0.0

        # MVP Drawdown & instability penalty are 0, but fields kept
        drawdown_penalty = 0.0
        instability_penalty = 0.0

        total_score = (0.5 * mean_20d) + (0.3 * mean_5d) + (0.2 * mean_1d) - drawdown_penalty - instability_penalty

        score_record = {
            "score_id": score_id,
            "tournament_id": args.tournament_id,
            "generation_id": runs_info["generation_id"],
            "prompt_set_id": ps_id,
            "data_mode": args.data_mode,
            "comparison_group": args.comparison_group,
            "memory_bank_version": args.memory_bank_version,
            "score_scope_id": args.score_scope_id,
            "episodes_count": runs_info["succeeded"] + runs_info["failed"],
            "succeeded_runs": runs_info["succeeded"],
            "failed_runs": runs_info["failed"],
            "mean_reward_1d": float(mean_1d),
            "mean_reward_5d": float(mean_5d),
            "mean_reward_20d": float(mean_20d),
            "drawdown_penalty": float(drawdown_penalty),
            "instability_penalty": float(instability_penalty),
            "total_score": float(total_score),
            "rank": None, # Will be set below
            "score_version": args.score_version,
            "created_at": pd.Timestamp.utcnow().isoformat()
        }

        scores_list.append(score_record)

    # Rank them
    scores_list.sort(key=lambda x: x["total_score"], reverse=True)
    for i, sc in enumerate(scores_list):
        sc["rank"] = i + 1
        save_jsonl_append(scores_path, sc)
        existing_scores[sc["score_id"]] = sc
        scores_added += 1

    logger.info(f"Added {scores_added} scores for tournament {args.tournament_id}")

    # Update manifest
    manifest = {
        "dataset_version": args.score_version,
        "count": len(existing_scores),
        "generated_at": pd.Timestamp.utcnow().isoformat()
    }
    with open(scores_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

if __name__ == "__main__":
    main()
