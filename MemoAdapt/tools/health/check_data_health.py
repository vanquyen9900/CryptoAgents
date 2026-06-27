"""Comprehensive data health check for MeMo Tournament pipeline."""
import os
import sys
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

DATALAKE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = DATALAKE_DIR / "data" / "memo_adaptation"

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"
INFO = "[INFO]"

total_pass = 0
total_fail = 0
total_warn = 0


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def check(label: str, condition: bool, detail: str = ""):
    global total_pass, total_fail
    status = PASS if condition else FAIL
    if condition:
        total_pass += 1
    else:
        total_fail += 1
    suffix = f" -- {detail}" if detail else ""
    print(f"  {status} {label}{suffix}")
    return condition


def warn(label: str, detail: str = ""):
    global total_warn
    total_warn += 1
    suffix = f" -- {detail}" if detail else ""
    print(f"  {WARN} {label}{suffix}")


def info(label: str, detail: str = ""):
    suffix = f" -- {detail}" if detail else ""
    print(f"  {INFO} {label}{suffix}")


def section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def extract_decision_from_report(report: str) -> str:
    """Extract trading decision from agent report text."""
    if not report:
        return ""
    for action in ["Overweight", "Underweight", "Buy", "Sell", "Hold"]:
        if re.search(rf'\b{action}\b', report, re.IGNORECASE):
            return action
    return ""


def main():
    # ============================================================
    # 1. BASE CONTEXT COVERAGE (inputs_ctx_paper_aligned_v1.jsonl)
    # ============================================================
    section("1. Base Context Coverage -- inputs_ctx_paper_aligned_v1.jsonl")
    inputs_path = DATA_DIR / "materialized_inputs" / "inputs_ctx_paper_aligned_v1.jsonl"
    inputs = load_jsonl(inputs_path)

    check("File exists", inputs_path.exists())
    check("Row count = 753", len(inputs) == 753, f"got {len(inputs)}")

    has_ticker_news = sum(1 for r in inputs if r.get("ticker_news_window") and len(r["ticker_news_window"]) > 0)
    has_macro_series = sum(1 for r in inputs if r.get("macro_snapshot") and len(r["macro_snapshot"]) > 0)
    has_social = sum(1 for r in inputs if r.get("social_window") and len(r["social_window"]) > 0)
    has_macro_news = sum(1 for r in inputs if r.get("macro_news_window") and len(r["macro_news_window"]) > 0)
    has_market_window = sum(1 for r in inputs if r.get("market_window") and len(r["market_window"]) > 0)
    has_technical = sum(1 for r in inputs if r.get("technical_window") and len(r["technical_window"]) > 0)
    has_financial = sum(1 for r in inputs if r.get("financial_statement_window") and len(r["financial_statement_window"]) > 0)
    # fundamentals_snapshot can be an empty dict; actual fundamentals data is in financial_statement_window
    has_fundamentals_snapshot = sum(1 for r in inputs if r.get("fundamentals_snapshot") and len(r["fundamentals_snapshot"]) > 0)

    check("ticker_news = 753", has_ticker_news == 753, f"got {has_ticker_news}")
    check("macro_series (macro_snapshot) = 753", has_macro_series == 753, f"got {has_macro_series}")
    check("social = 753", has_social == 753, f"got {has_social}")
    check("financial_statement_window ~= 631 (fundamentals proxy)", 600 <= has_financial <= 753, f"got {has_financial}")
    check("macro_news = 0 (acceptable, using macro_series)", has_macro_news == 0, f"got {has_macro_news}")
    check("market_window = 753", has_market_window == 753, f"got {has_market_window}")
    check("technical_window = 753", has_technical == 753, f"got {has_technical}")

    info("fundamentals_snapshot (profile dict)", f"{has_fundamentals_snapshot} non-empty (expected 0 or low)")

    # Check unique input IDs
    input_ids = [r.get("input_id") for r in inputs]
    check("Unique input_ids", len(set(input_ids)) == len(input_ids),
          f"{len(set(input_ids))} unique / {len(input_ids)} total")

    # Coverage summary
    coverage_data = defaultdict(int)
    for r in inputs:
        cov = r.get("coverage", {})
        for k, v in cov.items():
            if v:
                coverage_data[k] += 1
    if coverage_data:
        info("Coverage field summary", str(dict(coverage_data)))

    # ============================================================
    # 2. BASELINE TRAJECTORIES (workflow_trajectories.jsonl)
    # ============================================================
    section("2. Baseline Trajectories -- workflow_trajectories.jsonl")
    traj_path = DATA_DIR / "trajectories" / "workflow_trajectories.jsonl"
    trajectories = load_jsonl(traj_path)

    check("File exists", traj_path.exists())
    check("Row count = 2259", len(trajectories) == 2259, f"got {len(trajectories)}")

    succeeded = sum(1 for t in trajectories if t.get("run_status") == "succeeded")
    check("run_status=succeeded = 2259", succeeded == 2259, f"got {succeeded}")

    # Decision is in agent_outputs, not top-level
    has_decision = 0
    decisions = Counter()
    for t in trajectories:
        ao = t.get("agent_outputs", {})
        ftd = ao.get("final_trade_decision") or t.get("final_trade_decision")
        if not ftd:
            report = ao.get("investment_plan") or ao.get("market_report") or ""
            ftd = extract_decision_from_report(report)
        if ftd and str(ftd).strip():
            has_decision += 1
            decisions[str(ftd).strip()] += 1
        else:
            decisions["NO_DECISION"] += 1

    check("final_trade_decision extractable = 2259", has_decision == 2259, f"got {has_decision}")
    info("Decision distribution", str(dict(decisions)))

    # Filter checks
    tour_ids = set(t.get("tournament_id") for t in trajectories)
    check("tournament_id = tour_2022_gen0", tour_ids == {"tour_2022_gen0"}, f"got {tour_ids}")

    comp_groups = set(t.get("comparison_group") for t in trajectories)
    check("comparison_group = baseline_no_memory", comp_groups == {"baseline_no_memory"}, f"got {comp_groups}")

    ctx_policies = set(t.get("context_policy_id") for t in trajectories)
    check("context_policy_id = ctx_paper_aligned_v1", ctx_policies == {"ctx_paper_aligned_v1"}, f"got {ctx_policies}")

    mem_policies = set(t.get("memory_policy_id") for t in trajectories)
    check("memory_policy_id = mem_none_v1", mem_policies == {"mem_none_v1"}, f"got {mem_policies}")

    # Unique trajectory IDs
    traj_ids = [t.get("trajectory_id") for t in trajectories]
    check("Unique trajectory_ids", len(set(traj_ids)) == len(traj_ids),
          f"{len(set(traj_ids))} unique / {len(traj_ids)} total")

    # Prompt set distribution
    prompt_sets = Counter(t.get("prompt_set_id") for t in trajectories)
    info("Prompt set distribution", str(dict(prompt_sets)))
    check("3 prompt sets x 753 episodes = 2259",
          all(v == 753 for v in prompt_sets.values()) and len(prompt_sets) == 3,
          str(dict(prompt_sets)))

    # Symbol distribution
    symbols = Counter(t.get("symbol") for t in trajectories)
    info("Symbol distribution", str(dict(symbols)))

    # ============================================================
    # 3. REWARDS (trajectory_rewards.jsonl)
    # ============================================================
    section("3. Rewards -- trajectory_rewards.jsonl")
    rewards_path = DATA_DIR / "rewards" / "trajectory_rewards.jsonl"
    rewards = load_jsonl(rewards_path)

    check("File exists", rewards_path.exists())
    check("Row count = 6777", len(rewards) == 6777, f"got {len(rewards)}")
    check("2259 x 3 = 6777", len(rewards) == 2259 * 3, f"got {len(rewards)}")

    # Horizon distribution
    horizons = Counter(r.get("horizon_days") for r in rewards)
    info("Horizon distribution", str(dict(horizons)))
    horizon_keys = set(horizons.keys())
    check("Horizons 1, 5, 20 present",
          {1, 5, 20}.issubset(horizon_keys) or {"1", "5", "20"}.issubset({str(h) for h in horizon_keys}),
          f"got {horizon_keys}")

    # Check no None total_reward
    none_rewards = sum(1 for r in rewards if r.get("total_reward") is None)
    check("No total_reward=None", none_rewards == 0, f"got {none_rewards} None values")

    # Unique reward IDs
    reward_ids = [r.get("reward_id") for r in rewards]
    check("Unique reward_ids", len(set(reward_ids)) == len(reward_ids),
          f"{len(set(reward_ids))} unique / {len(reward_ids)} total")

    # FK check: all reward trajectory_ids exist in trajectories
    traj_id_set = set(traj_ids)
    reward_traj_ids = set(r.get("trajectory_id") for r in rewards)
    missing_traj = reward_traj_ids - traj_id_set
    check("All reward trajectory_ids ref valid trajectories", len(missing_traj) == 0,
          f"{len(missing_traj)} missing")

    # ============================================================
    # 4. TRUESKILL SCORES (tournament_scores.jsonl)
    # ============================================================
    section("4. TrueSkill Scores -- tournament_scores.jsonl")
    scores_path = DATA_DIR / "tournament_scores" / "tournament_scores.jsonl"
    scores = load_jsonl(scores_path)

    check("File exists", scores_path.exists())

    # Filter by scope
    scope_scores = [s for s in scores if s.get("score_scope_id") == "baseline_2022_full_trueskill_v2"]
    check("score_scope_id = baseline_2022_full_trueskill_v2", len(scope_scores) > 0,
          f"got {len(scope_scores)} rows")

    score_methods = set(s.get("score_method") for s in scope_scores)
    check("score_method = trueskill", score_methods == {"trueskill"}, f"got {score_methods}")
    check("3 rows for 3 prompt sets", len(scope_scores) == 3, f"got {len(scope_scores)}")

    for s in scope_scores:
        ps = s.get("prompt_set_id")
        mu = s.get("trueskill_mu")
        sigma = s.get("trueskill_sigma")
        matched = s.get("matched_state_count")
        skipped = s.get("skipped_state_count")
        info(f"  {ps}", f"mu={mu}, sigma={sigma}, matched={matched}, skipped={skipped}")

    matched_states_all = [s.get("matched_state_count") for s in scope_scores]
    check("matched_states = 753", all(m == 753 for m in matched_states_all), f"got {matched_states_all}")

    skipped_states_all = [s.get("skipped_state_count") for s in scope_scores]
    check("skipped_states = 0", all(s == 0 for s in skipped_states_all), f"got {skipped_states_all}")

    # ============================================================
    # 5. MEMORY BANK (memo_memory_bank.jsonl + manifest.json)
    # ============================================================
    section("5. Memory Bank -- memo_memory_bank.jsonl + manifest.json")
    memory_path = DATA_DIR / "memory_bank" / "memo_memory_bank.jsonl"
    manifest_path = DATA_DIR / "memory_bank" / "manifest.json"

    memory_exists = memory_path.exists()
    manifest_exists = manifest_path.exists()

    target_version = "mb_2022_full_highvar_trueskill_socialproxy_llm_v1"

    if not memory_exists:
        warn("memo_memory_bank.jsonl does NOT exist yet", "Memory builder may still be running")
    else:
        memories = load_jsonl(memory_path)
        check("memo_memory_bank.jsonl exists", True)
        info("Total memory rows", str(len(memories)))

        version_memories = [m for m in memories if m.get("memory_bank_version") == target_version]
        check(f"count_version_memories > 0 (version={target_version})", len(version_memories) > 0,
              f"got {len(version_memories)}")

        # Unique memory IDs
        mem_ids = [m.get("memory_id") for m in memories]
        check("Unique memory_ids", len(set(mem_ids)) == len(mem_ids),
              f"{len(set(mem_ids))} unique / {len(mem_ids)} total")

        # Quality scores
        quality_scores = [m.get("quality_score", 0) for m in version_memories]
        if quality_scores:
            info("Quality score range",
                 f"min={min(quality_scores):.3f}, max={max(quality_scores):.3f}, "
                 f"avg={sum(quality_scores)/len(quality_scores):.3f}")

        # Lesson types
        lesson_types = Counter(m.get("lesson_type") for m in version_memories)
        info("Lesson type distribution", str(dict(lesson_types)))

        # FK check: source trajectory/reward refs
        source_traj_ids_in_mem = set()
        source_reward_ids_in_mem = set()
        for m in version_memories:
            stids = m.get("source_trajectory_ids") or []
            srids = m.get("source_reward_ids") or []
            ev = m.get("evidence_summary", {})
            ev_tids = ev.get("example_trajectory_ids", [])
            ev_rids = ev.get("example_reward_ids", [])
            if isinstance(stids, list):
                source_traj_ids_in_mem.update(stids)
            if isinstance(srids, list):
                source_reward_ids_in_mem.update(srids)
            if isinstance(ev_tids, list):
                source_traj_ids_in_mem.update(ev_tids)
            if isinstance(ev_rids, list):
                source_reward_ids_in_mem.update(ev_rids)
            if m.get("source_trajectory_id"):
                source_traj_ids_in_mem.add(m["source_trajectory_id"])
            if m.get("source_reward_id"):
                source_reward_ids_in_mem.add(m["source_reward_id"])

        source_traj_ids_in_mem.discard(None)
        source_reward_ids_in_mem.discard(None)

        missing_traj_refs = source_traj_ids_in_mem - traj_id_set
        reward_id_set = set(reward_ids)
        missing_reward_refs = source_reward_ids_in_mem - reward_id_set

        if source_traj_ids_in_mem:
            check("Memory source_trajectory_ids ref valid trajectories",
                  len(missing_traj_refs) == 0,
                  f"{len(missing_traj_refs)} missing out of {len(source_traj_ids_in_mem)}")
        else:
            warn("No source_trajectory_ids found in memory records")

        if source_reward_ids_in_mem:
            check("Memory source_reward_ids ref valid rewards",
                  len(missing_reward_refs) == 0,
                  f"{len(missing_reward_refs)} missing out of {len(source_reward_ids_in_mem)}")
        else:
            warn("No source_reward_ids found in memory records")

    if manifest_exists:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        check("manifest.json exists", True)

        ds_version = manifest.get("dataset_version")
        check(f"dataset_version = {target_version}", ds_version == target_version, f"got {ds_version}")

        source_scope = manifest.get("source_score_scope_id")
        check("source_score_scope_id = baseline_2022_full_trueskill_v2",
              source_scope == "baseline_2022_full_trueskill_v2", f"got {source_scope}")

        sel_mode = manifest.get("selection_mode")
        check("selection_mode = trueskill_match", sel_mode == "trueskill_match", f"got {sel_mode}")

        state_gran = manifest.get("state_granularity")
        check("state_granularity = match", state_gran == "match", f"got {state_gran}")

        refl_mode = manifest.get("reflection_mode")
        check("reflection_mode = llm", refl_mode == "llm", f"got {refl_mode}")

        crud_mode = manifest.get("crud_mode")
        check("crud_mode = llm", crud_mode == "llm", f"got {crud_mode}")

        count_version = manifest.get("count_version_memories")
        check("count_version_memories > 0", count_version is not None and count_version > 0,
              f"got {count_version}")

        refl_errors = manifest.get("reflection_errors", -1)
        check("reflection_errors = 0 or very low",
              refl_errors is not None and refl_errors <= 3, f"got {refl_errors}")

        info("Manifest full dump", json.dumps(manifest, indent=2, default=str))
    else:
        warn("manifest.json does NOT exist yet", "Memory builder may still be running")

    # ============================================================
    # 6. EPISODES cross-check
    # ============================================================
    section("6. Episodes Cross-check")
    episodes_path = DATA_DIR / "episodes" / "trading_episodes.jsonl"
    episodes = load_jsonl(episodes_path)
    check("Episodes file exists", episodes_path.exists())
    info("Total episodes", str(len(episodes)))

    target_symbols = {"AAPL", "AMZN", "GOOGL"}
    filtered_episodes = [
        e for e in episodes
        if e.get("symbol") in target_symbols
        and "2022-01-03" <= e.get("analysis_time", "")[:10] <= "2022-12-30"
    ]
    check("Filtered episodes = 753", len(filtered_episodes) == 753, f"got {len(filtered_episodes)}")

    ep_symbols = Counter(e.get("symbol") for e in filtered_episodes)
    info("Episode symbol distribution", str(dict(ep_symbols)))

    # ============================================================
    # 7. VALIDATION SCRIPT (if exists)
    # ============================================================
    section("7. Validation Script Check")
    validator_path = DATALAKE_DIR / "tools" / "validation" / "validate_memo_tournament_dataset.py"
    if validator_path.exists():
        info("Validator script exists", str(validator_path))
    else:
        warn("validate_memo_tournament_dataset.py not found")

    # ============================================================
    # SUMMARY
    # ============================================================
    section("OVERALL SUMMARY")
    print(f"  Passed:   {total_pass}")
    print(f"  Failed:   {total_fail}")
    print(f"  Warnings: {total_warn}")
    print()

    if total_fail == 0:
        print("  ALL CHECKS PASSED!")
    else:
        print(f"  {total_fail} CHECKS FAILED - review above")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
