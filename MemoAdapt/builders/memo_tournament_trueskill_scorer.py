"""Score MeMo trading prompt sets with state-level TrueSkill matches.

This scorer keeps the existing financial rewards as the outcome signal, but
changes the fitness surface to a tournament: prompt sets are compared only
against other prompt sets that ran on the same symbol and analysis time.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

try:
    import trueskill
except ImportError as exc:  # pragma: no cover - exercised only in missing envs
    raise SystemExit(
        "Missing dependency 'trueskill'. Install it with `pip install trueskill` "
        "or use the tradingagents conda environment."
    ) from exc


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "memo_adaptation"
HORIZON_KEYS = ("1d", "5d", "20d")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def parse_reward_weights(raw: str) -> dict[str, float]:
    weights: dict[str, float] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError(f"Invalid reward weight item: {item!r}")
        key, value = item.split("=", 1)
        key = key.strip().lower()
        if key not in HORIZON_KEYS:
            raise ValueError(f"Unsupported reward horizon in weights: {key!r}")
        weights[key] = float(value.strip())

    missing = [key for key in HORIZON_KEYS if key not in weights]
    if missing:
        raise ValueError(f"Missing reward weights for: {', '.join(missing)}")

    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Reward weights must sum to a positive value")
    return {key: value / total for key, value in weights.items()}


def comparison_group_for(row: dict[str, Any]) -> str:
    explicit = row.get("comparison_group")
    if explicit:
        return str(explicit)
    return "baseline_no_memory" if row.get("memory_policy_id") == "mem_none_v1" else "memory_enabled"


def memory_bank_version_for(row: dict[str, Any]) -> str:
    explicit = row.get("memory_bank_version")
    if explicit:
        return str(explicit)
    return "none" if row.get("memory_policy_id") == "mem_none_v1" else "unknown"


def fnum(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def state_id_for(traj: dict[str, Any]) -> str:
    symbol = str(traj.get("symbol") or "UNKNOWN")
    analysis_time = str(traj.get("analysis_time") or traj.get("episode_id") or "unknown_time")
    return f"{symbol}|{analysis_time}"


def horizon_key(value: Any) -> str | None:
    text = str(value).strip().lower()
    if text.endswith("d"):
        return text if text in HORIZON_KEYS else None
    text = f"{text}d"
    return text if text in HORIZON_KEYS else None


def build_ranks(participants: list[dict[str, Any]], tie_eps: float) -> list[int]:
    ordered = sorted(
        ((idx, item["match_reward"]) for idx, item in enumerate(participants)),
        key=lambda pair: pair[1],
        reverse=True,
    )
    ranks = [0] * len(participants)
    current_rank = 0
    previous_reward: float | None = None

    for position, (idx, reward) in enumerate(ordered):
        if previous_reward is not None and abs(previous_reward - reward) > tie_eps:
            current_rank = position
        ranks[idx] = current_rank
        previous_reward = reward
    return ranks


def keep_trajectory(traj: dict[str, Any], args: argparse.Namespace) -> bool:
    if traj.get("tournament_id") != args.tournament_id:
        return False
    if args.data_mode and traj.get("data_mode") != args.data_mode:
        return False
    if args.comparison_group and comparison_group_for(traj) != args.comparison_group:
        return False
    if args.memory_bank_version and memory_bank_version_for(traj) != args.memory_bank_version:
        return False
    return True


def score_id_for(args: argparse.Namespace, prompt_set_id: str) -> str:
    scope = args.score_scope_id or "all"
    return f"score_{args.tournament_id}_{scope}_trueskill_{prompt_set_id}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Score prompt sets using MeMo-style TrueSkill tournament matches.")
    parser.add_argument("--tournament-id", required=True)
    parser.add_argument("--score-version", default="trueskill_v1")
    parser.add_argument("--data-mode", default=None)
    parser.add_argument("--comparison-group", default=None)
    parser.add_argument("--memory-bank-version", default=None)
    parser.add_argument("--score-scope-id", required=True)
    parser.add_argument("--reward-weights", default="1d=0.2,5d=0.3,20d=0.5")
    parser.add_argument("--min-candidates-per-match", type=int, default=2)
    parser.add_argument("--tie-eps", type=float, default=1e-12)
    parser.add_argument("--initial-mu", type=float, default=25.0)
    parser.add_argument("--initial-sigma", type=float, default=25.0 / 3.0)
    parser.add_argument("--beta", type=float, default=25.0 / 6.0)
    parser.add_argument("--tau", type=float, default=25.0 / 300.0)
    parser.add_argument("--draw-probability", type=float, default=0.10)
    parser.add_argument(
        "--replace-scope",
        action="store_true",
        help="Replace existing TrueSkill score rows for this tournament/scope/version.",
    )
    args = parser.parse_args()

    weights = parse_reward_weights(args.reward_weights)
    trajectories_path = DATA_DIR / "trajectories" / "workflow_trajectories.jsonl"
    rewards_path = DATA_DIR / "rewards" / "trajectory_rewards.jsonl"
    scores_path = DATA_DIR / "tournament_scores" / "tournament_scores.jsonl"
    manifest_path = DATA_DIR / "tournament_scores" / "manifest.json"

    trajectories = load_jsonl(trajectories_path)
    rewards = load_jsonl(rewards_path)
    if not trajectories:
        logger.error("No trajectories found at %s", trajectories_path)
        return 1
    if not rewards:
        logger.error("No rewards found at %s", rewards_path)
        return 1

    selected_by_id = {
        str(traj["trajectory_id"]): traj
        for traj in trajectories
        if traj.get("trajectory_id") and keep_trajectory(traj, args)
    }
    logger.info("Selected %d trajectories for TrueSkill scoring", len(selected_by_id))
    if not selected_by_id:
        logger.error("No trajectories matched the requested filters.")
        return 1

    rewards_by_trajectory: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for reward in rewards:
        traj_id = str(reward.get("trajectory_id") or "")
        if traj_id not in selected_by_id:
            continue
        key = horizon_key(reward.get("horizon_days"))
        total_reward = fnum(reward.get("total_reward"))
        if key and total_reward is not None:
            rewards_by_trajectory[traj_id][key] = reward

    runs_by_prompt: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"succeeded": 0, "failed": 0, "generation_id": None, "trajectories": 0}
    )
    financial_rewards: dict[str, dict[str, list[float]]] = defaultdict(lambda: {key: [] for key in HORIZON_KEYS})
    matches: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for traj_id, traj in selected_by_id.items():
        prompt_set_id = str(traj.get("prompt_set_id") or "unknown")
        runs = runs_by_prompt[prompt_set_id]
        runs["generation_id"] = runs["generation_id"] or traj.get("generation_id")
        runs["trajectories"] += 1
        if traj.get("run_status") == "succeeded":
            runs["succeeded"] += 1
        else:
            runs["failed"] += 1
            continue

        horizon_rewards = rewards_by_trajectory.get(traj_id, {})
        if not all(key in horizon_rewards for key in HORIZON_KEYS):
            continue

        per_horizon = {
            key: float(horizon_rewards[key]["total_reward"])
            for key in HORIZON_KEYS
        }
        for key, value in per_horizon.items():
            financial_rewards[prompt_set_id][key].append(value)

        match_reward = sum(weights[key] * per_horizon[key] for key in HORIZON_KEYS)
        matches[state_id_for(traj)].append(
            {
                "trajectory_id": traj_id,
                "prompt_set_id": prompt_set_id,
                "match_reward": match_reward,
                "per_horizon": per_horizon,
            }
        )

    env = trueskill.TrueSkill(
        mu=args.initial_mu,
        sigma=args.initial_sigma,
        beta=args.beta,
        tau=args.tau,
        draw_probability=args.draw_probability,
    )
    ratings = {
        prompt_set_id: env.create_rating()
        for prompt_set_id in runs_by_prompt
    }
    match_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "matches_played": 0,
            "first_place": 0,
            "strict_first_place": 0,
            "last_place": 0,
            "tied_matches": 0,
            "rank_sum": 0.0,
            "match_rewards": [],
        }
    )

    matched_state_count = 0
    skipped_state_count = 0
    for state_id in sorted(matches):
        participants = sorted(matches[state_id], key=lambda item: item["prompt_set_id"])
        if len(participants) < args.min_candidates_per_match:
            skipped_state_count += 1
            continue

        ranks = build_ranks(participants, args.tie_eps)
        rating_groups = [(ratings[item["prompt_set_id"]],) for item in participants]
        updated = env.rate(rating_groups, ranks=ranks)
        matched_state_count += 1

        max_rank = max(ranks)
        rank_counts = defaultdict(int)
        for rank in ranks:
            rank_counts[rank] += 1

        for item, rank, new_group in zip(participants, ranks, updated, strict=True):
            prompt_set_id = item["prompt_set_id"]
            ratings[prompt_set_id] = new_group[0]
            stats = match_stats[prompt_set_id]
            stats["matches_played"] += 1
            stats["rank_sum"] += rank
            stats["match_rewards"].append(item["match_reward"])
            if rank == 0:
                stats["first_place"] += 1
                if rank_counts[rank] == 1:
                    stats["strict_first_place"] += 1
            if rank == max_rank:
                stats["last_place"] += 1
            if rank_counts[rank] > 1:
                stats["tied_matches"] += 1

    if matched_state_count == 0:
        logger.error("No match had enough candidates for TrueSkill update.")
        return 1

    existing_scores = load_jsonl(scores_path)
    new_score_ids = {score_id_for(args, prompt_set_id) for prompt_set_id in runs_by_prompt}
    if args.replace_scope:
        remaining_scores = [
            row for row in existing_scores
            if row.get("score_id") not in new_score_ids
        ]
    else:
        existing_ids = {str(row.get("score_id")) for row in existing_scores}
        duplicate_ids = new_score_ids & existing_ids
        if duplicate_ids:
            logger.error(
                "TrueSkill scores already exist for this scope/version. Use --replace-scope to refresh. Examples: %s",
                sorted(duplicate_ids)[:3],
            )
            return 1
        remaining_scores = existing_scores

    score_rows: list[dict[str, Any]] = []
    for prompt_set_id, runs in runs_by_prompt.items():
        rating = ratings[prompt_set_id]
        stats = match_stats[prompt_set_id]
        matches_played = int(stats["matches_played"])
        means = {
            key: mean(values) if values else 0.0
            for key, values in financial_rewards[prompt_set_id].items()
        }
        financial_score = sum(weights[key] * means[key] for key in HORIZON_KEYS)
        avg_rank = (stats["rank_sum"] / matches_played) if matches_played else None
        match_win_rate = (stats["strict_first_place"] / matches_played) if matches_played else 0.0
        match_top_rate = (stats["first_place"] / matches_played) if matches_played else 0.0

        score_rows.append(
            {
                "score_id": score_id_for(args, prompt_set_id),
                "tournament_id": args.tournament_id,
                "generation_id": runs["generation_id"],
                "prompt_set_id": prompt_set_id,
                "data_mode": args.data_mode,
                "comparison_group": args.comparison_group,
                "memory_bank_version": args.memory_bank_version,
                "score_scope_id": args.score_scope_id,
                "score_method": "trueskill",
                "reward_weights": weights,
                "episodes_count": int(runs["trajectories"]),
                "succeeded_runs": int(runs["succeeded"]),
                "failed_runs": int(runs["failed"]),
                "matches_played": matches_played,
                "matched_state_count": matched_state_count,
                "skipped_state_count": skipped_state_count,
                "mean_match_reward": float(mean(stats["match_rewards"])) if stats["match_rewards"] else 0.0,
                "mean_reward_1d": float(means["1d"]),
                "mean_reward_5d": float(means["5d"]),
                "mean_reward_20d": float(means["20d"]),
                "financial_score": float(financial_score),
                "drawdown_penalty": 0.0,
                "instability_penalty": 0.0,
                "trueskill_mu": float(rating.mu),
                "trueskill_sigma": float(rating.sigma),
                "trueskill_conservative": float(rating.mu - 3.0 * rating.sigma),
                "match_win_rate": float(match_win_rate),
                "match_top_rate": float(match_top_rate),
                "match_first_place_count": int(stats["first_place"]),
                "match_strict_first_place_count": int(stats["strict_first_place"]),
                "match_last_place_count": int(stats["last_place"]),
                "match_tied_count": int(stats["tied_matches"]),
                "mean_match_rank": float(avg_rank) if avg_rank is not None else None,
                "total_score": float(rating.mu),
                "rank": None,
                "score_version": args.score_version,
                "created_at": utc_now(),
            }
        )

    score_rows.sort(key=lambda row: row["trueskill_mu"], reverse=True)
    for index, row in enumerate(score_rows, start=1):
        row["rank"] = index

    all_scores = remaining_scores + score_rows
    write_jsonl(scores_path, all_scores)
    manifest = {
        "dataset_version": args.score_version,
        "count": len(all_scores),
        "generated_at": utc_now(),
        "latest_score_method": "trueskill",
        "latest_score_scope_id": args.score_scope_id,
        "latest_matched_state_count": matched_state_count,
        "latest_skipped_state_count": skipped_state_count,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    logger.info(
        "Wrote %d TrueSkill score rows for %d matched states (%d skipped states)",
        len(score_rows),
        matched_state_count,
        skipped_state_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
