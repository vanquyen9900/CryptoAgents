import subprocess
import sys
import argparse
from pathlib import Path

DATALAKE_DIR = Path(__file__).resolve().parents[2]

def run_step(cmd, step_name):
    print(f"\n{'='*60}")
    print(f"Executing: {step_name}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=str(DATALAKE_DIR), shell=True)
    if result.returncode != 0:
        print(f"FAIL: {step_name} exited with code {result.returncode}")
        sys.exit(1)
    print(f"SUCCESS: {step_name}")

def main():
    parser = argparse.ArgumentParser(description="Orchestrate MeMo Tournament Pipeline.")
    parser.add_argument("--phase", choices=["seed", "pilot", "score-pilot", "gen1", "score-gen1", "champion", "validate"], required=True)
    args = parser.parse_args()

    python_exe = sys.executable

    if args.phase == "seed":
        run_step(f"{python_exe} builders/memo_tournament_seed_builder.py", "Seed Gen0")

    elif args.phase == "pilot":
        run_step(f"{python_exe} run_memo_tournament.py --generation-id gen_2022_00 --tournament-id tour_2022_gen0 --start-date 2022-03-01 --end-date 2022-03-31 --symbols AAPL AMZN GOOGL --prompt-set-ids ps_default_v1 ps_risk_aware_v1 ps_macro_defensive_v1 --max-runs 250 --resume", "Run Pilot (March 2022)")

    elif args.phase == "score-pilot":
        run_step(f"{python_exe} builders/memo_reward_builder.py --tournament-id tour_2022_gen0", "Build Rewards for Gen0")
        run_step(f"{python_exe} builders/memo_tournament_scorer.py --tournament-id tour_2022_gen0", "Score Tournament Gen0")

    elif args.phase == "gen1":
        run_step(f"{python_exe} builders/memo_memory_extractor.py --tournament-id tour_2022_gen0", "Extract Memory Bank")
        run_step(f"{python_exe} builders/memo_prompt_evolver.py --parent-generation-id gen_2022_00 --new-generation-id gen_2022_01 --source-tournament-id tour_2022_gen0", "Evolve Gen1")

    elif args.phase == "score-gen1":
        run_step(f"{python_exe} builders/memo_reward_builder.py --tournament-id tour_2022_gen1", "Build Rewards for Gen1")
        run_step(f"{python_exe} builders/memo_tournament_scorer.py --tournament-id tour_2022_gen1", "Score Tournament Gen1")

    elif args.phase == "champion":
        run_step(f"{python_exe} builders/memo_champion_selector.py --generation-id gen_2022_01 --tournament-id tour_2022_gen1", "Select Champion")

    elif args.phase == "validate":
        run_step(f"{python_exe} tools/validation/validate_memo_tournament_dataset.py", "Validate Dataset")

if __name__ == "__main__":
    main()
