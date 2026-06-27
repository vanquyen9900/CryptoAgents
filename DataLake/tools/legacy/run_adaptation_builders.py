import subprocess
import sys
import os
from pathlib import Path

CONTEXT_POLICY_ID = "ctx_paper_aligned_v1"

def run():
    print("Starting MEMO Adaptation Builders (legacy orchestration)...")
    builders_dir = Path(__file__).resolve().parents[2] / "builders"

    # 1. Materialize Inputs
    print("\n--- Running Paper-Aligned Materialize Inputs Builder (Phase 1) ---")
    res = subprocess.run([
        sys.executable,
        str(builders_dir / "materialize_inputs_paper_aligned.py"),
        "--context-policy-id",
        CONTEXT_POLICY_ID,
    ])
    if res.returncode != 0: raise SystemExit("Materialize Inputs Builder failed.")

    # 2. Trading Episodes
    print("\n--- Running Trading Episodes Builder (Phase 2) ---")
    res = subprocess.run([sys.executable, str(builders_dir / "memo_episode_builder.py")])
    if res.returncode != 0: raise SystemExit("Trading Episodes Builder failed.")

    # 3-5. Policies
    print("\n--- Running Policy Builder (Phases 3-5) ---")
    res = subprocess.run([sys.executable, str(builders_dir / "policy_builder.py")])
    if res.returncode != 0: raise SystemExit("Policy Builder failed.")

    # 6. Adaptation Runs
    print("\n--- Running Adaptation Run Builder (Phase 6) ---")
    res = subprocess.run([sys.executable, str(builders_dir / "adaptation_run_builder.py")])
    if res.returncode != 0: raise SystemExit("Adaptation Run Builder failed.")

    print("\nAll adaptation builders finished.")

if __name__ == "__main__":
    run()
