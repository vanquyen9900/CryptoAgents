import os
import json
from pathlib import Path

DATALAKE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = DATALAKE_DIR / "data" / "memo_adaptation"

def load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records

def print_result(check_name: str, passed: bool, details: str = ""):
    status = "PASS" if passed else "FAIL"
    msg = f"[{status}] {check_name}"
    if details:
        msg += f" - {details}"
    print(msg)
    return passed

def validate_unique_keys(records: list, key_field: str, filename: str) -> bool:
    keys = [r.get(key_field) for r in records if r.get(key_field)]
    unique_keys = set(keys)
    passed = len(keys) == len(unique_keys)
    if not passed:
        duplicates = [k for k in unique_keys if keys.count(k) > 1]
        print_result(f"Unique keys in {filename} ({key_field})", passed, f"Found duplicates: {duplicates[:3]}")
    else:
        print_result(f"Unique keys in {filename} ({key_field})", passed, f"{len(keys)} unique records")
    return passed

def check_foreign_key(records: list, fk_field: str, valid_keys: set, filename: str, allow_empty=False) -> bool:
    invalid = []
    for r in records:
        val = r.get(fk_field)
        if val is None and allow_empty:
            continue
        if isinstance(val, list):
            for v in val:
                if v not in valid_keys:
                    invalid.append(v)
        else:
            if val not in valid_keys:
                invalid.append(val)

    passed = len(invalid) == 0
    if not passed:
        print_result(f"Foreign key {fk_field} in {filename}", passed, f"Invalid keys found: {list(set(invalid))[:3]}")
    else:
        print_result(f"Foreign key {fk_field} in {filename}", passed)
    return passed

def main():
    print("=== MeMo Tournament Dataset Validation ===")

    ps_recs = load_jsonl(DATA_DIR / "prompt_sets" / "prompt_sets.jsonl")
    gen_recs = load_jsonl(DATA_DIR / "prompt_generations" / "prompt_generations.jsonl")
    tour_recs = load_jsonl(DATA_DIR / "tournaments" / "tournaments.jsonl")
    traj_recs = load_jsonl(DATA_DIR / "trajectories" / "workflow_trajectories.jsonl")
    rew_recs = load_jsonl(DATA_DIR / "rewards" / "trajectory_rewards.jsonl")
    score_recs = load_jsonl(DATA_DIR / "tournament_scores" / "tournament_scores.jsonl")
    mem_recs = load_jsonl(DATA_DIR / "memory_bank" / "memo_memory_bank.jsonl")
    champ_recs = load_jsonl(DATA_DIR / "champions" / "champion_prompt_sets.jsonl")

    all_passed = True

    # 1. Unique Keys
    all_passed &= validate_unique_keys(ps_recs, "prompt_set_id", "prompt_sets.jsonl")
    all_passed &= validate_unique_keys(gen_recs, "generation_id", "prompt_generations.jsonl")
    all_passed &= validate_unique_keys(tour_recs, "tournament_id", "tournaments.jsonl")
    all_passed &= validate_unique_keys(traj_recs, "trajectory_id", "workflow_trajectories.jsonl")
    all_passed &= validate_unique_keys(rew_recs, "reward_id", "trajectory_rewards.jsonl")
    all_passed &= validate_unique_keys(score_recs, "score_id", "tournament_scores.jsonl")
    all_passed &= validate_unique_keys(mem_recs, "memory_id", "memo_memory_bank.jsonl")
    all_passed &= validate_unique_keys(champ_recs, "champion_id", "champion_prompt_sets.jsonl")

    print("\n--- Foreign Key Checks ---")
    ps_keys = {r["prompt_set_id"] for r in ps_recs}
    gen_keys = {r["generation_id"] for r in gen_recs}
    tour_keys = {r["tournament_id"] for r in tour_recs}
    traj_keys = {r["trajectory_id"] for r in traj_recs}
    rew_keys = {r["reward_id"] for r in rew_recs}
    mem_keys = {r["memory_id"] for r in mem_recs}

    if ps_keys:
        all_passed &= check_foreign_key(gen_recs, "prompt_set_ids", ps_keys, "prompt_generations.jsonl")
        all_passed &= check_foreign_key(tour_recs, "prompt_set_ids", ps_keys, "tournaments.jsonl")
        all_passed &= check_foreign_key(traj_recs, "prompt_set_id", ps_keys, "workflow_trajectories.jsonl")
        all_passed &= check_foreign_key(rew_recs, "prompt_set_id", ps_keys, "trajectory_rewards.jsonl")
        all_passed &= check_foreign_key(score_recs, "prompt_set_id", ps_keys, "tournament_scores.jsonl")

    if gen_keys:
        all_passed &= check_foreign_key(tour_recs, "generation_id", gen_keys, "tournaments.jsonl")

    if tour_keys:
        all_passed &= check_foreign_key(traj_recs, "tournament_id", tour_keys, "workflow_trajectories.jsonl")

    if traj_keys:
        all_passed &= check_foreign_key(rew_recs, "trajectory_id", traj_keys, "trajectory_rewards.jsonl")
        all_passed &= check_foreign_key(mem_recs, "source_trajectory_id", traj_keys, "memo_memory_bank.jsonl")

    if rew_keys:
        all_passed &= check_foreign_key(mem_recs, "source_reward_id", rew_keys, "memo_memory_bank.jsonl")

    print("\n--- Summary ---")
    if all_passed:
        print("ALL CHECKS PASSED. Dataset is clean.")
    else:
        print("SOME CHECKS FAILED. Please review the output above.")

if __name__ == "__main__":
    main()
