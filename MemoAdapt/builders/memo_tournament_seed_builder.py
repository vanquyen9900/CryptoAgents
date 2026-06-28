import json
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "memo_adaptation"

FOLDERS = [
    "prompt_sets",
    "prompt_generations",
    "tournaments",
    "trajectories",
    "rewards",
    "tournament_scores",
    "memory_bank",
    "champions/selection_reports",
    "dry_runs",
]

def load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records

def save_jsonl(path: Path, records: list):
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")

def init_manifest(path: Path):
    if not path.exists():
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "dataset_version": "v0.1",
                "count": 0,
                "generated_at": pd.Timestamp.utcnow().isoformat()
            }, f, indent=2)

def update_manifest(path: Path, count: int):
    manifest = {
        "dataset_version": "v0.1",
        "count": count,
        "generated_at": pd.Timestamp.utcnow().isoformat()
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

def seed_prompt_sets():
    out_dir = DATA_DIR / "prompt_sets"
    out_file = out_dir / "prompt_sets.jsonl"
    manifest_file = out_dir / "manifest.json"

    existing = load_jsonl(out_file)
    existing_ids = {r["prompt_set_id"] for r in existing}

    now = pd.Timestamp.utcnow().isoformat()

    seeds = [
        {
            "prompt_set_id": "ps_default_v1",
            "generation": 0,
            "description": "Baseline prompt set with minimal additions",
            "role_patches": {
                "all": "Follow standard procedures. Always state your evidence clearly. Highlight assumptions and uncertainty. Do not use any future data."
            },
            "created_from": "seed",
            "parent_prompt_set_ids": [],
            "created_from_memory_ids": [],
            "created_at": now
        },
        {
            "prompt_set_id": "ps_risk_aware_v1",
            "generation": 0,
            "description": "Risk-aware prompt set for bear market behavior",
            "role_patches": {
                "all": "Follow standard procedures. Always state your evidence clearly. Highlight assumptions and uncertainty. Do not use any future data.",
                "market_analyst": "Pay attention to trend breakdown, volatility expansion, failed rebounds, and price behavior relative to SMA50/SMA200.",
                "trader": "Prefer risk-adjusted decisions. Avoid catching falling knives without confirmation from trend, volume, and risk/reward.",
                "risk_team": "Stress-test downside scenarios before approving directional exposure."
            },
            "created_from": "seed",
            "parent_prompt_set_ids": [],
            "created_from_memory_ids": [],
            "created_at": now
        },
        {
            "prompt_set_id": "ps_macro_defensive_v1",
            "generation": 0,
            "description": "Macro defensive prompt set for rate/inflation shocks",
            "role_patches": {
                "all": "Follow standard procedures. Always state your evidence clearly. Highlight assumptions and uncertainty. Do not use any future data.",
                "news_analyst": "Treat macro/rate regime and inflation pressure as first-class evidence.",
                "fundamentals_analyst": "Treat macro/rate regime and earnings pressure as first-class evidence.",
                "research_manager": "If technical rebound conflicts with macro/rate pressure, explicitly resolve the conflict before giving an investment plan.",
                "trader": "Be conservative when valuation compression and macro risk dominate short-term price strength."
            },
            "created_from": "seed",
            "parent_prompt_set_ids": [],
            "created_from_memory_ids": [],
            "created_at": now
        }
    ]

    added = 0
    for seed in seeds:
        if seed["prompt_set_id"] not in existing_ids:
            existing.append(seed)
            added += 1

    if added > 0:
        save_jsonl(out_file, existing)
    update_manifest(manifest_file, len(existing))
    print(f"Added {added} seed prompt sets. Total: {len(existing)}")

def seed_generations():
    out_dir = DATA_DIR / "prompt_generations"
    out_file = out_dir / "prompt_generations.jsonl"
    manifest_file = out_dir / "manifest.json"

    existing = load_jsonl(out_file)
    existing_ids = {r["generation_id"] for r in existing}

    now = pd.Timestamp.utcnow().isoformat()

    gen0 = {
        "generation_id": "gen_2022_00",
        "training_window": {
            "start_date": "2022-01-03",
            "end_date": "2022-12-30"
        },
        "population_size": 3,
        "prompt_set_ids": [
            "ps_default_v1",
            "ps_risk_aware_v1",
            "ps_macro_defensive_v1"
        ],
        "created_by": "seed",
        "created_at": now
    }

    added = 0
    if gen0["generation_id"] not in existing_ids:
        existing.append(gen0)
        added += 1

    if added > 0:
        save_jsonl(out_file, existing)
    update_manifest(manifest_file, len(existing))
    print(f"Added {added} generation. Total: {len(existing)}")

def seed_tournaments():
    out_dir = DATA_DIR / "tournaments"
    out_file = out_dir / "tournaments.jsonl"
    manifest_file = out_dir / "manifest.json"

    existing = load_jsonl(out_file)
    existing_ids = {r["tournament_id"] for r in existing}

    now = pd.Timestamp.utcnow().isoformat()

    tour0 = {
        "tournament_id": "tour_2022_gen0",
        "generation_id": "gen_2022_00",
        "training_window": {
            "start_date": "2022-01-03",
            "end_date": "2022-12-30"
        },
        "episode_filter": {
            "symbols": ["AAPL", "AMZN", "GOOGL"],
            "start_date": "2022-01-03",
            "end_date": "2022-12-30"
        },
        "prompt_set_ids": [
            "ps_default_v1",
            "ps_risk_aware_v1",
            "ps_macro_defensive_v1"
        ],
        "status": "planned",
        "created_at": now
    }

    added = 0
    if tour0["tournament_id"] not in existing_ids:
        existing.append(tour0)
        added += 1

    if added > 0:
        save_jsonl(out_file, existing)
    update_manifest(manifest_file, len(existing))
    print(f"Added {added} tournament. Total: {len(existing)}")

def main():
    print("Starting MeMo Tournament Seed Builder...")

    for folder in FOLDERS:
        d = DATA_DIR / folder
        d.mkdir(parents=True, exist_ok=True)
        # Create empty manifests for data directories to make validators happy
        if "selection_reports" not in folder:
            init_manifest(d / "manifest.json")

    seed_prompt_sets()
    seed_generations()
    seed_tournaments()

    print("Done seeding Gen0.")

if __name__ == "__main__":
    main()
