import os
import sys
import json
import pandas as pd
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import DATA_DIR

def build_adaptation_runs():
    print("Building Adaptation Runs (Phase 6)...")

    episodes_path = DATA_DIR / "memo_adaptation" / "episodes" / "trading_episodes.jsonl"
    if not episodes_path.exists():
        print("No trading_episodes.jsonl found.")
        return

    out_dir = DATA_DIR / "memo_adaptation" / "adaptation_runs"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / "adaptation_runs.jsonl"

    # MVP run plan combinations
    combinations = [
        # Baseline
        ("ctx_default_v1", "mem_none_v1", ["prompt_default_v1"]),
        # Memory test
        ("ctx_default_v1", "mem_top5_role_v1", ["prompt_default_v1"]),
        # Context tests
        ("ctx_short_market_v1", "mem_none_v1", ["prompt_default_v1"]),
        ("ctx_long_market_v1", "mem_none_v1", ["prompt_default_v1"]),
        # Prompt tests
        ("ctx_default_v1", "mem_none_v1", ["prompt_evidence_based_v1"]),
        ("ctx_default_v1", "mem_top5_role_v1", ["prompt_memory_aware_v1"]),
    ]

    count = 0
    with open(episodes_path, "r", encoding="utf-8") as f_in, open(out_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip(): continue
            episode = json.loads(line)

            episode_id = episode["episode_id"]
            input_id = episode["input_id"]

            for ctx, mem, prompts in combinations:
                prompt_str = "_".join(prompts)
                run_id = f"run_{episode_id}_{ctx}_{mem}_{prompt_str}"

                record = {
                    "adaptation_run_id": run_id,
                    "episode_id": episode_id,
                    "input_id": input_id,
                    "context_policy_id": ctx,
                    "memory_policy_id": mem,
                    "prompt_variant_ids": prompts,
                    "target_workflow": "tradingagents",
                    "status": "planned",
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

    print(f"Generated {count} adaptation runs.")

if __name__ == "__main__":
    build_adaptation_runs()
