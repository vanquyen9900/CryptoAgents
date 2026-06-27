import argparse
import json
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DATALAKE_DIR = Path(__file__).resolve().parents[2]

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

def validate_time_leak(records, date_field="known_time"):
    """Check that known_time <= analysis_time for all records in a window."""
    for rec in records:
        kt = rec.get(date_field)
        at = rec.get("_analysis_time")
        if kt and at and kt > at:
            return False
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-policy-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    args = parser.parse_args()

    inputs_path = DATALAKE_DIR / "data" / "memo_adaptation" / "materialized_inputs" / f"inputs_{args.context_policy_id}.jsonl"

    if not inputs_path.exists():
        print(f"File not found: {inputs_path}")
        return

    records = load_jsonl(inputs_path)

    # Filter records based on symbols and date range
    filtered = []
    for r in records:
        trade_date = r.get("analysis_time", "")[:10]
        if r.get("symbol") in args.symbols and args.start_date <= trade_date <= args.end_date:
            filtered.append(r)

    if not filtered:
        print("No records found matching filters.")
        return

    print(f"=== Validating Context Policy {args.context_policy_id} ({len(filtered)} records) ===")

    all_passed = True

    # Check 1: input_policy_id matches
    bad_policy = [r for r in filtered if r.get("input_policy_id") != args.context_policy_id]
    all_passed &= print_result("input_policy_id matches", len(bad_policy) == 0, f"{len(bad_policy)} mismatches")

    # Pre-process analysis_time for inner checks
    for r in filtered:
        at = r.get("analysis_time")
        for k in r.keys():
            if isinstance(r[k], list):
                for item in r[k]:
                    if isinstance(item, dict):
                        item["_analysis_time"] = at
            elif isinstance(r[k], dict) and k == "macro_snapshot":
                for item in r[k].values():
                    if isinstance(item, dict):
                        item["_analysis_time"] = at

    # Checks for time leakage
    leaks = 0
    mkt_len = 0
    tech_len = 0
    t_news_len = 0
    m_news_len = 0
    soc_len = 0
    sen_len = 0

    for r in filtered:
        if not validate_time_leak(r.get("market_window", []), "trade_date"): leaks += 1
        if not validate_time_leak(r.get("technical_window", []), "trade_date"): leaks += 1
        if not validate_time_leak(r.get("ticker_news_window", []), "known_time"): leaks += 1
        if not validate_time_leak(r.get("macro_news_window", []), "known_time"): leaks += 1
        if not validate_time_leak(r.get("social_window", []), "known_time"): leaks += 1
        if not validate_time_leak(list(r.get("macro_snapshot", {}).values()), "observation_date"): leaks += 1

        if len(r.get("market_window", [])) > 15: mkt_len += 1
        if len(r.get("technical_window", [])) > 15: tech_len += 1
        if len(r.get("ticker_news_window", [])) > 50: t_news_len += 1
        if len(r.get("macro_news_window", [])) > 30: m_news_len += 1
        if len(r.get("social_window", [])) > 50: soc_len += 1

    all_passed &= print_result("No time leakage (known_time <= analysis_time)", leaks == 0, f"{leaks} leaked windows")
    all_passed &= print_result("Market window <= 15 rows", mkt_len == 0, f"{mkt_len} violations")
    all_passed &= print_result("Technical window <= 15 rows", tech_len == 0, f"{tech_len} violations")
    all_passed &= print_result("Ticker news <= 50 materialized", t_news_len == 0, f"{t_news_len} violations")
    all_passed &= print_result("Macro news <= 30 materialized", m_news_len == 0, f"{m_news_len} violations")
    all_passed &= print_result("Social window <= 50 materialized", soc_len == 0, f"{soc_len} violations")

    print("\n--- Summary ---")
    if all_passed:
        print("ALL CHECKS PASSED. Context policy is compliant.")
    else:
        print("SOME CHECKS FAILED.")

if __name__ == "__main__":
    main()
