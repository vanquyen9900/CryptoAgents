import argparse
import json
import logging
from pathlib import Path
import pandas as pd

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
                record_id = record.get("score_id") or record.get("prompt_set_id")
                if record_id:
                    records[record_id] = record
    return records

def save_jsonl_append(path: Path, record: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

def main():
    parser = argparse.ArgumentParser(description="Select Champion Prompt Set.")
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--tournament-id", required=True)
    parser.add_argument("--score-scope-id", default=None)
    parser.add_argument("--score-method", default=None)
    parser.add_argument("--score-version", default=None)
    args = parser.parse_args()

    scores_path = DATA_DIR / "tournament_scores" / "tournament_scores.jsonl"
    prompt_sets_path = DATA_DIR / "prompt_sets" / "prompt_sets.jsonl"
    champions_path = DATA_DIR / "champions" / "champion_prompt_sets.jsonl"
    report_dir = DATA_DIR / "champions" / "selection_reports"

    scores = load_jsonl(scores_path)
    prompt_sets = load_jsonl(prompt_sets_path)

    def keep_score(score):
        if score.get("tournament_id") != args.tournament_id:
            return False
        if args.generation_id and score.get("generation_id") != args.generation_id:
            return False
        if args.score_scope_id and score.get("score_scope_id") != args.score_scope_id:
            return False
        if args.score_method and score.get("score_method", "financial") != args.score_method:
            return False
        if args.score_version and score.get("score_version") != args.score_version:
            return False
        return True

    tour_scores = [s for s in scores.values() if keep_score(s)]
    if not tour_scores:
        logger.error(f"No scores found for {args.tournament_id} with requested filters.")
        return

    best_score = max(tour_scores, key=lambda x: x["total_score"])
    best_ps_id = best_score["prompt_set_id"]
    best_ps = prompt_sets.get(best_ps_id)

    if not best_ps:
        logger.error(f"Best prompt set {best_ps_id} not found.")
        return

    now = pd.Timestamp.utcnow().isoformat()

    champion_record = {
        "champion_id": f"champ_{args.tournament_id}_{args.score_scope_id or 'all'}_{args.score_method or 'any'}",
        "tournament_id": args.tournament_id,
        "generation_id": args.generation_id,
        "prompt_set_id": best_ps_id,
        "role_patches": best_ps.get("role_patches", {}),
        "score_id": best_score.get("score_id"),
        "score_scope_id": best_score.get("score_scope_id"),
        "selection_method": best_score.get("score_method", "financial"),
        "total_score": best_score["total_score"],
        "financial_score": best_score.get("financial_score"),
        "trueskill_mu": best_score.get("trueskill_mu"),
        "trueskill_sigma": best_score.get("trueskill_sigma"),
        "match_win_rate": best_score.get("match_win_rate"),
        "mean_reward_20d": best_score["mean_reward_20d"],
        "mean_reward_5d": best_score["mean_reward_5d"],
        "mean_reward_1d": best_score["mean_reward_1d"],
        "selected_at": now,
        "status": "active"
    }

    # Check if champion already selected for this tournament
    existing_champs = load_jsonl(champions_path) if champions_path.exists() else {}
    if champion_record["champion_id"] not in [c.get("champion_id") for c in existing_champs.values()]:
        save_jsonl_append(champions_path, champion_record)
        logger.info(f"Champion {best_ps_id} saved.")
    else:
        logger.info(f"Champion already selected for {args.tournament_id}.")

    # Generate Markdown Report
    report_dir.mkdir(parents=True, exist_ok=True)
    report_suffix = f"{args.tournament_id}_{args.score_scope_id or 'all'}_{args.score_method or 'any'}"
    report_path = report_dir / f"champion_report_{report_suffix}.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Champion Selection Report: {args.tournament_id}\n\n")
        f.write(f"**Selected At**: {now}\n")
        f.write(f"**Generation**: {args.generation_id}\n\n")
        f.write(f"**Score Scope**: `{best_score.get('score_scope_id')}`\n")
        f.write(f"**Selection Method**: `{best_score.get('score_method', 'financial')}`\n\n")

        f.write("## 🏆 Champion Prompt Set\n\n")
        f.write(f"- **ID**: `{best_ps_id}`\n")
        f.write(f"- **Total Score**: {best_score['total_score']:.4f}\n")
        if best_score.get("score_method") == "trueskill":
            f.write(f"- **TrueSkill Mu**: {best_score.get('trueskill_mu', 0.0):.4f}\n")
            f.write(f"- **TrueSkill Sigma**: {best_score.get('trueskill_sigma', 0.0):.4f}\n")
            f.write(f"- **Match Win Rate**: {best_score.get('match_win_rate', 0.0):.4f}\n")
            f.write(f"- **Financial Score**: {best_score.get('financial_score', 0.0):.6f}\n")
        f.write(f"- **Win/Loss**: {best_score['succeeded_runs']} / {best_score['failed_runs']}\n")
        f.write(f"- **20d Return**: {best_score['mean_reward_20d']:.4f}\n")

        f.write("\n### Winning Role Patches\n\n```json\n")
        f.write(json.dumps(best_ps.get("role_patches", {}), indent=2))
        f.write("\n```\n\n")

        f.write("## 📊 Leaderboard\n\n")
        if best_score.get("score_method") == "trueskill":
            f.write("| Rank | Prompt Set ID | Mu | Sigma | Win Rate | Financial | 20d Reward | Runs |\n")
            f.write("|---|---|---|---|---|---|---|---|\n")
        else:
            f.write("| Rank | Prompt Set ID | Score | 20d Reward | 5d Reward | 1d Reward | Runs |\n")
            f.write("|---|---|---|---|---|---|---|\n")

        sorted_scores = sorted(tour_scores, key=lambda x: x["total_score"], reverse=True)
        for idx, sc in enumerate(sorted_scores):
            if best_score.get("score_method") == "trueskill":
                f.write(f"| {idx+1} | `{sc['prompt_set_id']}` | {sc.get('trueskill_mu', 0.0):.4f} | {sc.get('trueskill_sigma', 0.0):.4f} | {sc.get('match_win_rate', 0.0):.4f} | {sc.get('financial_score', 0.0):.6f} | {sc['mean_reward_20d']:.4f} | {sc['succeeded_runs']} |\n")
            else:
                f.write(f"| {idx+1} | `{sc['prompt_set_id']}` | {sc['total_score']:.4f} | {sc['mean_reward_20d']:.4f} | {sc['mean_reward_5d']:.4f} | {sc['mean_reward_1d']:.4f} | {sc['succeeded_runs']} |\n")

    logger.info(f"Report written to {report_path}")

if __name__ == "__main__":
    main()
