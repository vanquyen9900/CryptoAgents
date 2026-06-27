import subprocess
import sys
from pathlib import Path

DATALAKE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(DATALAKE_DIR))

from adapters.decision_ledger import (
    build_decision_ledger_context,
    current_exposure_from_prior,
    exposure_after_action,
    parse_action,
)
from adapters.memo_memory import format_retrieved_memories


class Contract:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, name, condition, details=""):
        if condition:
            print(f"[PASS] {name}{' - ' + details if details else ''}")
            self.passed += 1
        else:
            print(f"[FAIL] {name}{' - ' + details if details else ''}")
            self.failed += 1

    def finish(self):
        print("\n--- Summary ---")
        print(f"PASS={self.passed} FAIL={self.failed}")
        if self.failed:
            raise SystemExit(1)


def main():
    contract = Contract()

    contract.check("parse_action extracts Hold", parse_action("Rating: Hold\nRationale: wait") == "Hold")
    contract.check("Buy sets exposure long", exposure_after_action("Buy", 0.0) == 1.0)
    contract.check("Hold preserves exposure", exposure_after_action("Hold", 1.0) == 1.0)
    contract.check("Sell moves to cash", exposure_after_action("Sell", 1.0) == 0.0)

    trajectories = [
        {
            "trajectory_id": "old_a",
            "tournament_id": "tour_2024_q1_eval",
            "comparison_group": "test_q1_2024_baseline_no_memory",
            "prompt_set_id": "ps_default_v1",
            "symbol": "AAPL",
            "analysis_time": "2024-01-02T21:00:00+00:00",
            "run_status": "succeeded",
            "agent_outputs": {
                "final_trade_decision": "Rating: Buy\nRationale: constructive setup",
                "investment_plan": "Constructive setup with improving trend.",
            },
        },
        {
            "trajectory_id": "future_a",
            "tournament_id": "tour_2024_q1_eval",
            "comparison_group": "test_q1_2024_baseline_no_memory",
            "prompt_set_id": "ps_default_v1",
            "symbol": "AAPL",
            "analysis_time": "2024-01-04T21:00:00+00:00",
            "run_status": "succeeded",
            "agent_outputs": {
                "final_trade_decision": "Rating: Sell",
                "investment_plan": "Future row must not be visible.",
            },
        },
    ]
    prior = [trajectories[0]]
    contract.check("current exposure replays prior actions", current_exposure_from_prior(prior) == 1.0)
    context, exposure, source_ids = build_decision_ledger_context(
        trajectories=trajectories,
        tournament_id="tour_2024_q1_eval",
        comparison_group="test_q1_2024_baseline_no_memory",
        prompt_set_id="ps_default_v1",
        symbol="AAPL",
        analysis_time="2024-01-03T21:00:00+00:00",
    )
    contract.check("ledger includes prior trajectory", "old_a" in context and source_ids == ["old_a"])
    contract.check("ledger excludes future trajectory", "future_a" not in context)
    contract.check("ledger exposes current exposure", exposure == 1.0 and "1.00" in context)

    memory_text = format_retrieved_memories(
        [
            {
                "memory_id": "m1",
                "memory_bank_version": "mb_test",
                "content": "Content-only weekly lesson should render.",
                "use_when": ["similar mixed evidence"],
                "avoid_when": ["assuming history repeats"],
            }
        ]
    )
    contract.check("memory formatter falls back to content", "Content-only weekly lesson should render." in memory_text)
    contract.check("memory formatter warns situational prior", "situational prior" in memory_text)

    experiment_text = (DATALAKE_DIR / "run_q1_2024_experiment.py").read_text(encoding="utf-8")
    runner_text = (DATALAKE_DIR / "run_memo_tournament.py").read_text(encoding="utf-8")
    contract.check("Q1 orchestrator uses offline_full_pipeline", "offline_full_pipeline" in experiment_text)
    contract.check("runner exposes offline_full_pipeline mode", "offline_full_pipeline" in runner_text)
    contract.check(
        "offline full pipeline routes analyst stages to quick model",
        "market_report = call(\n        quick_llm" in runner_text
        and "news_report = call(\n        quick_llm" in runner_text
        and "fundamentals_report = call(\n        quick_llm" in runner_text,
    )
    contract.check(
        "offline full pipeline routes intermediate decision stages to quick model",
        "investment_plan = call(\n        quick_llm" in runner_text
        and "trader_plan = call(\n        quick_llm" in runner_text
        and "risk_debate = call(\n        quick_llm" in runner_text,
    )
    contract.check(
        "offline full pipeline routes final decision to deep model",
        "final_decision_text = call(\n        deep_llm" in runner_text,
    )
    contract.check(
        "runner records decision ledger source ids",
        "decision_ledger_source_ids" in runner_text and "current_exposure_before_decision" in runner_text,
    )

    help_result = subprocess.run(
        [sys.executable, str(DATALAKE_DIR / "run_memo_tournament.py"), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    contract.check("runner --help works", help_result.returncode == 0)
    contract.check("runner --help lists offline_full_pipeline", "offline_full_pipeline" in help_result.stdout)

    contract.finish()


if __name__ == "__main__":
    main()
