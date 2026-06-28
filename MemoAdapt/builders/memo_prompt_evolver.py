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
                record_id = record.get("score_id") or record.get("prompt_set_id") or record.get("memory_id")
                if record_id:
                    records[record_id] = record
    return records

def save_jsonl_append(path: Path, record: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

def main():
    parser = argparse.ArgumentParser(description="Generate Gen1 prompt sets.")
    parser.add_argument("--parent-generation-id", required=True)
    parser.add_argument("--new-generation-id", required=True)
    parser.add_argument("--source-tournament-id", required=True)
    args = parser.parse_args()

    scores_path = DATA_DIR / "tournament_scores" / "tournament_scores.jsonl"
    prompt_sets_path = DATA_DIR / "prompt_sets" / "prompt_sets.jsonl"
    memory_path = DATA_DIR / "memory_bank" / "memo_memory_bank.jsonl"
    generations_path = DATA_DIR / "prompt_generations" / "prompt_generations.jsonl"
    tournaments_path = DATA_DIR / "tournaments" / "tournaments.jsonl"

    scores = load_jsonl(scores_path)
    prompt_sets = load_jsonl(prompt_sets_path)
    memories = load_jsonl(memory_path)
    generations = load_jsonl(generations_path)
    existing_tournaments = load_jsonl(tournaments_path)

    # 1. Find best Gen0 prompt set
    tour_scores = [s for s in scores.values() if s.get("tournament_id") == args.source_tournament_id]
    if not tour_scores:
        logger.error(f"No scores found for {args.source_tournament_id}")
        return

    best_score = max(tour_scores, key=lambda x: x["total_score"])
    best_ps_id = best_score["prompt_set_id"]
    best_ps = prompt_sets.get(best_ps_id)

    if not best_ps:
        logger.error(f"Best prompt set {best_ps_id} not found.")
        return

    now = pd.Timestamp.utcnow().isoformat()
    new_prompt_sets = []

    # ps_gen1_keep_best
    ps_keep_best = {
        "prompt_set_id": "ps_gen1_keep_best",
        "generation": 1,
        "description": f"Copied from best Gen0 prompt set: {best_ps_id}",
        "role_patches": best_ps["role_patches"].copy(),
        "created_from": "evolution",
        "parent_prompt_set_ids": [best_ps_id],
        "created_from_memory_ids": [],
        "created_at": now
    }
    new_prompt_sets.append(ps_keep_best)

    # ps_gen1_memory_guided
    tour_memories = [m for m in memories.values() if m.get("source_tournament_id") == args.source_tournament_id]
    top_memories = sorted(tour_memories, key=lambda x: x["quality_score"], reverse=True)[:5]

    memory_patches = "\n".join([f"- {m['lesson']} (Use when: {', '.join(m.get('use_when', []))})" for m in top_memories])

    role_patches_mem = best_ps["role_patches"].copy()
    role_patches_mem["trader"] = role_patches_mem.get("trader", "") + f"\n\nHistorical lessons:\n{memory_patches}"

    ps_memory_guided = {
        "prompt_set_id": "ps_gen1_memory_guided",
        "generation": 1,
        "description": "Guided by top memory lessons from Gen0",
        "role_patches": role_patches_mem,
        "created_from": "evolution",
        "parent_prompt_set_ids": [best_ps_id],
        "created_from_memory_ids": [m["memory_id"] for m in top_memories],
        "created_at": now
    }
    new_prompt_sets.append(ps_memory_guided)

    # ps_gen1_error_corrected
    worst_memories = sorted([m for m in tour_memories if m["quality_score"] > 0.85 and "massive drawdown" in m["lesson"]], key=lambda x: x["quality_score"], reverse=True)[:5]
    error_patches = "\n".join([f"- AVOID: {m['lesson']} (Avoid when: {', '.join(m.get('avoid_when', []))})" for m in worst_memories])

    role_patches_err = best_ps["role_patches"].copy()
    role_patches_err["risk_team"] = role_patches_err.get("risk_team", "") + f"\n\nError patterns to avoid:\n{error_patches}"

    ps_error_corrected = {
        "prompt_set_id": "ps_gen1_error_corrected",
        "generation": 1,
        "description": "Error corrected based on massive drawdowns from Gen0",
        "role_patches": role_patches_err,
        "created_from": "evolution",
        "parent_prompt_set_ids": [best_ps_id],
        "created_from_memory_ids": [m["memory_id"] for m in worst_memories],
        "created_at": now
    }
    new_prompt_sets.append(ps_error_corrected)

    # Save prompt sets
    existing_ps_ids = prompt_sets.keys()
    added_ps = 0
    for ps in new_prompt_sets:
        if ps["prompt_set_id"] not in existing_ps_ids:
            save_jsonl_append(prompt_sets_path, ps)
            added_ps += 1

    # Save generation
    gen_record = {
        "generation_id": args.new_generation_id,
        "parent_generation_id": args.parent_generation_id,
        "training_window": {
            "start_date": "2022-01-03",
            "end_date": "2022-12-30"
        },
        "population_size": 3,
        "prompt_set_ids": [ps["prompt_set_id"] for ps in new_prompt_sets],
        "created_by": "evolution",
        "evolution_operators": ["keep_best", "memory_guided", "trajectory_error_corrected"],
        "created_at": now
    }

    gen_ids = [g.get("generation_id") for g in generations.values() if "generation_id" in g]
    if args.new_generation_id not in gen_ids:
        save_jsonl_append(generations_path, gen_record)
        logger.info(f"Added generation {args.new_generation_id}")

    # Save tournament
    tour_id = f"tour_2022_gen1"
    tour_record = {
        "tournament_id": tour_id,
        "generation_id": args.new_generation_id,
        "training_window": {
            "start_date": "2022-01-03",
            "end_date": "2022-12-30"
        },
        "episode_filter": {
            "symbols": ["AAPL", "AMZN", "GOOGL"],
            "start_date": "2022-01-03",
            "end_date": "2022-12-30"
        },
        "prompt_set_ids": [ps["prompt_set_id"] for ps in new_prompt_sets],
        "status": "planned",
        "created_at": now
    }

    if tour_id not in existing_tournaments:
        save_jsonl_append(tournaments_path, tour_record)
        logger.info(f"Added tournament {tour_id}")

    logger.info(f"Added {added_ps} Gen1 prompt sets.")

if __name__ == "__main__":
    main()
