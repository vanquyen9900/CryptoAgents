import os
import json
import argparse
import logging
from datetime import datetime
import pandas as pd
import uuid

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
DEFAULT_TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_test_2024_q1")

def load_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

def init_empty_memory_bank(args):
    """Initialize an empty memory bank version. Doesn't really need to do anything but log."""
    logging.info(f"Initialized empty memory bank for version: {args.memory_bank_version}")

def generate_weekly_lesson(trajectories, week_start, week_end):
    """
    Synthesize a weekly lesson from the trajectories.
    In a full LLM implementation, this would pass context to an LLM.
    Here we use a rule-based summary of the actions taken.
    """
    if not trajectories:
        return None

    actions = []
    for t in trajectories:
        decision = t.get("agent_outputs", {}).get("final_trade_decision", "HOLD")
        sym = t.get("symbol")
        actions.append(f"{sym}: {decision}")

    action_counts = pd.Series(actions).value_counts().to_dict()

    lesson_text = (
        f"For setups resembling the week {week_start} to {week_end}, compare the current "
        "technical/news evidence against the recent decision ledger before changing exposure. "
        "Avoid treating momentum alone as sufficient; require support/resistance, risk, and "
        "macro/social confirmation before increasing or reducing a position."
    )
    lesson_content = (
        f"Weekly Reflection ({week_start} to {week_end}):\n"
        f"Actions taken: {action_counts}\n"
        f"Situational lesson: {lesson_text}"
    )

    # Ensure created_at and visible_from are strictly after week_end for contract tests
    # If week_end is "2024-01-05", created_at/visible_from could be "2024-01-06T00:00:00Z"
    post_week = week_end + "T23:59:59.001Z"

    return {
        "memory_id": f"mem_wk_{uuid.uuid4().hex[:8]}",
        "lesson": lesson_text,
        "content": lesson_content,
        "lesson_type": "weekly_decision_reflection",
        "agent_role": "trader",
        "symbol": "ANY",
        "market_regime": "mixed_regime",
        "use_when": [
            "The current setup resembles recent Q1-2024 decision patterns.",
            "The final decision agent is choosing whether to change portfolio exposure.",
            "Evidence is mixed and the prior decision ledger matters for interpreting Hold.",
        ],
        "avoid_when": [
            "Using the lesson as evidence that a past year or week must repeat.",
            "Ignoring current point-in-time market, news, macro, and portfolio-state evidence.",
        ],
        "recommended_adjustment": "Use as a soft prior for final buy/sell/hold decision only.",
        "quality_score": 0.5,
        "target_state": "mixed_regime|ma_unknown|rsi_unknown|macd_unknown",
        "created_at": post_week,
        "visible_from": post_week,
        "source_type": "weekly_reflection",
        "week_start": week_start + "T00:00:00Z" if len(week_start) == 10 else week_start,
        "week_end": week_end + "T23:59:59Z" if len(week_end) == 10 else week_end
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tournament-id")
    parser.add_argument("--comparison-group")
    parser.add_argument("--memory-bank-version", required=True)
    parser.add_argument("--week-start")
    parser.add_argument("--week-end")
    parser.add_argument("--seed-memory-bank-version", default=None)
    parser.add_argument("--init-empty-memory-bank", action="store_true")
    parser.add_argument("--reflection-mode", default="rule_based")
    parser.add_argument("--crud-mode", default="simple_add")
    parser.add_argument("--data-dir", default=DEFAULT_TEST_DATA_DIR)
    args = parser.parse_args()

    memory_path = os.path.join(args.data_dir, "memo_adaptation", "memory_bank", "memo_memory_bank.jsonl")

    if args.init_empty_memory_bank:
        init_empty_memory_bank(args)
        # Ensure file exists
        if not os.path.exists(memory_path):
            write_jsonl(memory_path, [])
        return

    if not args.week_start or not args.week_end or not args.tournament_id or not args.comparison_group:
        logging.error("Missing arguments for weekly reflection.")
        return

    # Load trajectories
    traj_path = os.path.join(args.data_dir, "memo_adaptation", "trajectories", "workflow_trajectories.jsonl")
    if not os.path.exists(traj_path):
        traj_path = os.path.join(args.data_dir, "trajectories", "workflow_trajectories.jsonl")

    trajectories = load_jsonl(traj_path)

    # Filter trajectories for the week
    week_trajs = []
    for t in trajectories:
        if t.get("tournament_id") == args.tournament_id and t.get("comparison_group") == args.comparison_group:
            date_str = str(t.get("analysis_time", ""))[:10]
            if args.week_start <= date_str <= args.week_end:
                week_trajs.append(t)

    logging.info(f"Found {len(week_trajs)} trajectories for week {args.week_start} to {args.week_end}")

    lesson = generate_weekly_lesson(week_trajs, args.week_start, args.week_end)

    memories_all = load_jsonl(memory_path)

    # If seed is provided and this is the FIRST week (i.e. no existing memories for this version),
    # we should copy the seed memories.
    current_version_memories = [m for m in memories_all if m.get("memory_bank_version") == args.memory_bank_version]

    if len(current_version_memories) == 0 and args.seed_memory_bank_version:
        seed_memories = [m for m in memories_all if m.get("memory_bank_version") == args.seed_memory_bank_version]
        for m in seed_memories:
            new_m = m.copy()
            new_m["memory_bank_version"] = args.memory_bank_version
            # DO NOT change memory_id so it links back to original if needed, or change it to avoid collision.
            # Changing it to avoid unique key constraints.
            new_m["memory_id"] = f"{new_m['memory_id']}_seed"
            memories_all.append(new_m)
        logging.info(f"Seeded {len(seed_memories)} memories from {args.seed_memory_bank_version}")

    new_memories_added = 0
    if lesson:
        lesson["memory_bank_version"] = args.memory_bank_version
        memories_all.append(lesson)
        new_memories_added += 1

    write_jsonl(memory_path, memories_all)

    # Save a separate markdown report of the lesson
    lessons_dir = os.path.join(args.data_dir, "memo_adaptation", "memory_bank", "weekly_lessons")
    os.makedirs(lessons_dir, exist_ok=True)
    if lesson:
        with open(os.path.join(lessons_dir, f"{args.memory_bank_version}_{args.week_end}.md"), "w") as f:
            f.write(f"# Weekly Lesson: {args.week_start} to {args.week_end}\n\n")
            f.write(lesson["content"] + "\n")

    logging.info(f"Added {new_memories_added} new weekly lessons. Total memories updated in {memory_path}.")

if __name__ == "__main__":
    main()
