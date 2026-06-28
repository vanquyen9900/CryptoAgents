import argparse
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

# Adjust paths to import TradingAgents and local adapters
THIS_DIR = Path(__file__).resolve().parent
BASE_DIR = THIS_DIR.parent
TRADINGAGENTS_DIR = BASE_DIR / "TradingAgents"
sys.path.insert(0, str(THIS_DIR))
sys.path.insert(0, str(TRADINGAGENTS_DIR))

# The tournament runner is launched from the repository root, while the active
# TradingAgents .env lives under TradingAgents/.env. Load it explicitly before
# importing DEFAULT_CONFIG so env overrides are applied.
try:
    from dotenv import load_dotenv

    load_dotenv(TRADINGAGENTS_DIR / ".env", override=False)
except ImportError:
    pass

# Import TradingAgents (ensure TRADINGAGENTS_LLM_PROVIDER etc. are set in env)
try:
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.llm_clients import create_llm_client
    HAS_TRADINGAGENTS = True
except ImportError:
    HAS_TRADINGAGENTS = False
    print("Warning: TradingAgents package not found in PYTHONPATH. Will use a mock runner.")

try:
    from langchain_core.messages import HumanMessage, SystemMessage
except ImportError:
    HumanMessage = None
    SystemMessage = None

from adapters.tradingagents_prompt_patch import get_prompt_patch
from adapters.memo_memory import (
    format_retrieved_memories,
    load_memory_bank,
    load_memory_policy,
    retrieve_memories_for_context,
)
from adapters.decision_ledger import build_decision_ledger_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = THIS_DIR / "data" / "memo_adaptation"
def sanitize_id_part(value) -> str:
    """Return a stable ID fragment that is safe for JSONL primary keys."""
    if value is None:
        return "none"
    text = str(value).strip()
    if not text:
        return "none"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


def make_trajectory_id(
    tournament_id: str,
    episode_id: str,
    prompt_set_id: str,
    data_mode: str,
    comparison_group: str,
    memory_policy_id: str,
    memory_bank_version: str,
) -> str:
    """Build trajectory IDs without colliding baseline and memory-enabled runs.

    Existing baseline trajectories intentionally keep their historical IDs so
    resume/scoring remain backward compatible with the first baseline run.
    Memory-enabled runs add comparison/memory suffixes because they are a
    different experimental condition and must not overwrite baseline rows.
    """
    mode_suffix = "" if data_mode == "tradingagents_tools" else f"_{sanitize_id_part(data_mode)}"
    base_id = f"traj_{tournament_id}_{episode_id}_{prompt_set_id}{mode_suffix}"
    is_legacy_baseline = (
        comparison_group == "baseline_no_memory"
        and memory_policy_id == "mem_none_v1"
        and memory_bank_version in (None, "", "none")
    )
    if is_legacy_baseline:
        return base_id
    return "_".join(
        [
            base_id,
            sanitize_id_part(comparison_group),
            sanitize_id_part(memory_policy_id),
            sanitize_id_part(memory_bank_version),
        ]
    )

def load_jsonl(path: Path) -> dict:
    if not path.exists():
        return {}
    records = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                # Use standard ID fields if available
                record_id = record.get("trajectory_id") or record.get("episode_id") or record.get("input_id") or record.get("prompt_set_id") or record.get("tournament_id")
                if record_id:
                    records[record_id] = record
    return records

def save_jsonl_append(path: Path, record: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")

def upsert_jsonl(path: Path, key: str, record: dict):
    rows = []
    replaced = False
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                existing = json.loads(line)
                if existing.get(key) == record.get(key):
                    if not replaced:
                        rows.append(record)
                        replaced = True
                else:
                    rows.append(existing)
    if not replaced:
        rows.append(record)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")

def save_json(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)

def format_materialized_context(input_data: dict, policy_id: str = "ctx_default_v1") -> str:
    """Format the materialized input into a compact markdown string."""
    if not input_data:
        return "No materialized input available."

    lines = [
        f"### Point-in-time Context for {input_data.get('symbol')} at {input_data.get('analysis_time')}",
        "This data is strictly point-in-time. Do not use future knowledge.",
        ""
    ]

    if policy_id == "ctx_paper_aligned_v1":
        # Compact market
        if "latest_market_snapshot" in input_data and input_data["latest_market_snapshot"]:
            lines.append("#### Latest Market Snapshot")
            m = input_data["latest_market_snapshot"]
            lines.append(f"Date: {m.get('trade_date')}, Close: {m.get('close')}, Volume: {m.get('volume')}")

        if "market_window" in input_data and input_data["market_window"]:
            lines.append("#### Recent Market Window (Last 15 trading rows)")
            for m in input_data["market_window"][-15:]:
                lines.append(f"Date: {m.get('trade_date')}, Close: {m.get('close')}, Vol: {m.get('volume')}")

        # Compact technical
        if "technical_window" in input_data and input_data["technical_window"]:
            lines.append("\n#### Technical Window (Last 15 trading rows)")
            for t in input_data["technical_window"][-15:]:
                lines.append(f"Date: {t.get('trade_date')}, RSI: {t.get('rsi')}, MACD: {t.get('macd')}, SMA20: {t.get('sma_20')}, SMA50: {t.get('sma_50')}, SMA200: {t.get('sma_200')}")

        # Fundamentals
        if "fundamentals_snapshot" in input_data and input_data["fundamentals_snapshot"]:
            lines.append("\n#### Fundamentals Snapshot")
            f = input_data["fundamentals_snapshot"]
            lines.append(f"Sector: {f.get('sector')}, Industry: {f.get('industry')}, Market Cap: {f.get('market_cap')}")

        if "financial_statement_window" in input_data and input_data["financial_statement_window"]:
            lines.append("\n#### Financial Statement Window (Latest 8 quarters)")
            items = input_data["financial_statement_window"][:40]
            for i in items:
                lines.append(f"{i.get('fiscal_year')}-{i.get('fiscal_period')} {i.get('statement_type')} {i.get('line_item')}: {i.get('value')} {i.get('currency')}")

        # News
        if "ticker_news_window" in input_data and input_data["ticker_news_window"]:
            lines.append("\n#### Ticker News (Top 20 ranked items)")
            for n in input_data["ticker_news_window"][:20]:
                lines.append(f"[{n.get('event_time')}] {n.get('title')} (Source: {n.get('source')}, Relevance: {n.get('relevance_score')})")

        if "macro_news_window" in input_data and input_data["macro_news_window"]:
            lines.append("\n#### Macro News (Top 10 ranked items)")
            for n in input_data["macro_news_window"][:10]:
                lines.append(f"[{n.get('event_time')}] {n.get('title')}")

        # Social
        if "social_window" in input_data and input_data["social_window"]:
            lines.append("\n#### Social and Sentiment (Top 15 items)")
            for s in input_data["social_window"][:15]:
                lines.append(f"[{s.get('known_time')}] {s.get('title', s.get('summary', ''))} (Sentiment: {s.get('sentiment')}, Score: {s.get('score')})")

        # Macro
        if "macro_snapshot" in input_data and input_data["macro_snapshot"]:
            lines.append("\n#### Macro Indicators Snapshot")
            for series_id, obs in input_data["macro_snapshot"].items():
                lines.append(f"{series_id}: {obs.get('value')} (as of {obs.get('observation_date')})")

    else:
        # Default policy formatting
        if "technical_snapshot" in input_data:
            lines.append("#### Technical Snapshot")
            lines.append(json.dumps(input_data["technical_snapshot"], indent=2))

        if "fundamentals_snapshot" in input_data:
            lines.append("#### Fundamentals Snapshot")
            lines.append(json.dumps(input_data["fundamentals_snapshot"], indent=2))

        if "macro_snapshot" in input_data:
            lines.append("#### Macro Snapshot")
            lines.append(json.dumps(input_data["macro_snapshot"], indent=2))

    return "\n".join(lines)

def format_offline_materialized_context(input_data: dict, policy_id: str = "ctx_default_v1", market_window_rows: int = 30) -> str:
    """Format the materialized input into a compact markdown string."""
    if not input_data:
        return "No materialized input available."

    lines = [
        f"### Point-in-time Context for {input_data.get('symbol')} at {input_data.get('analysis_time')}",
        "This data is strictly point-in-time. Do not use future knowledge.",
        ""
    ]

    if policy_id == "ctx_paper_aligned_v1":
        if "latest_market_snapshot" in input_data and input_data["latest_market_snapshot"]:
            lines.append("#### Latest Market Snapshot")
            m = input_data["latest_market_snapshot"]
            lines.append(f"Date: {m.get('trade_date')}, Close: {m.get('close')}, Volume: {m.get('volume')}")

        if "market_window" in input_data and input_data["market_window"]:
            lines.append(f"#### Recent Market Window (Last {market_window_rows} trading rows)")
            for m in input_data["market_window"][-market_window_rows:]:
                lines.append(f"Date: {m.get('trade_date')}, Close: {m.get('close')}, Vol: {m.get('volume')}")

        if "technical_window" in input_data and input_data["technical_window"]:
            lines.append("\n#### Technical Window (Last 15 trading rows)")
            for t in input_data["technical_window"][-15:]:
                lines.append(f"Date: {t.get('trade_date')}, RSI: {t.get('rsi')}, MACD: {t.get('macd')}, SMA20: {t.get('sma_20')}, SMA50: {t.get('sma_50')}, SMA200: {t.get('sma_200')}")

        if "fundamentals_snapshot" in input_data and input_data["fundamentals_snapshot"]:
            lines.append("\n#### Fundamentals Snapshot")
            f = input_data["fundamentals_snapshot"]
            lines.append(f"Sector: {f.get('sector')}, Industry: {f.get('industry')}, Market Cap: {f.get('market_cap')}")

        if "financial_statement_window" in input_data and input_data["financial_statement_window"]:
            lines.append("\n#### Financial Statement Window (Latest 8 quarters)")
            items = input_data["financial_statement_window"][:40]
            for i in items:
                lines.append(f"{i.get('fiscal_year')}-{i.get('fiscal_period')} {i.get('statement_type')} {i.get('line_item')}: {i.get('value')} {i.get('currency')}")

        if "ticker_news_window" in input_data and input_data["ticker_news_window"]:
            lines.append("\n#### Ticker News (Top 20 ranked items)")
            for n in input_data["ticker_news_window"][:20]:
                lines.append(f"[{n.get('event_time')}] {n.get('title')} (Source: {n.get('source')}, Relevance: {n.get('relevance_score')})")

        if "macro_news_window" in input_data and input_data["macro_news_window"]:
            lines.append("\n#### Macro News (Top 10 ranked items)")
            for n in input_data["macro_news_window"][:10]:
                lines.append(f"[{n.get('event_time')}] {n.get('title')}")

        if "social_window" in input_data and input_data["social_window"]:
            lines.append("\n#### Social and Sentiment (Top 15 items)")
            for s in input_data["social_window"][:15]:
                lines.append(f"[{s.get('known_time')}] {s.get('title', s.get('summary', ''))} (Sentiment: {s.get('sentiment')}, Score: {s.get('score')})")

        if "macro_snapshot" in input_data and input_data["macro_snapshot"]:
            lines.append("\n#### Macro Indicators Snapshot")
            for series_id, obs in input_data["macro_snapshot"].items():
                lines.append(f"{series_id}: {obs.get('value')} (as of {obs.get('observation_date')})")

        if "coverage" in input_data:
            lines.append("\n#### Dataset Coverage")
            lines.append(json.dumps(input_data["coverage"], indent=2))

        if "source_refs" in input_data:
            lines.append("\n#### Source Refs")
            lines.append(json.dumps(input_data["source_refs"], indent=2))

    else:
        # Default policy formatting
        if "latest_market_snapshot" in input_data and input_data["latest_market_snapshot"]:
            lines.append("#### Latest Market Snapshot")
            lines.append(json.dumps(input_data["latest_market_snapshot"], indent=2))

        if "market_window" in input_data and input_data["market_window"]:
            lines.append(f"#### Recent Market Window (Last {market_window_rows} trading rows)")
            mkt_subset = input_data["market_window"][-market_window_rows:]
            lines.append(json.dumps(mkt_subset, indent=2))

        if "technical_snapshot" in input_data:
            lines.append("#### Technical Snapshot")
            lines.append(json.dumps(input_data["technical_snapshot"], indent=2))

        if "fundamentals_snapshot" in input_data:
            lines.append("#### Fundamentals Profile")
            lines.append(json.dumps(input_data["fundamentals_snapshot"], indent=2))

        if "coverage" in input_data:
            lines.append("#### Dataset Coverage")
            lines.append(json.dumps(input_data["coverage"], indent=2))

        if "source_refs" in input_data:
            lines.append("#### Source References")
            lines.append(json.dumps(input_data["source_refs"], indent=2))

    return "\n".join(lines)

def estimate_tokens(text: str) -> int:
    """Rough token estimate for quota planning when provider metadata is absent."""
    if not text:
        return 0
    return max(1, int(len(text) / 4))

def extract_usage(message) -> tuple[int | None, int | None]:
    """Best-effort token usage extraction from LangChain/OpenAI-compatible messages."""
    usage = getattr(message, "usage_metadata", None) or {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if input_tokens is not None or output_tokens is not None:
        return input_tokens, output_tokens

    metadata = getattr(message, "response_metadata", None) or {}
    token_usage = metadata.get("token_usage") or metadata.get("usage") or {}
    input_tokens = (
        token_usage.get("prompt_tokens")
        or token_usage.get("input_tokens")
    )
    output_tokens = (
        token_usage.get("completion_tokens")
        or token_usage.get("output_tokens")
    )
    return input_tokens, output_tokens

def parse_offline_decision(text: str) -> str:
    if not text:
        return ""
    rating_match = re.search(r"(?:rating|action|decision)\s*[:\-]\s*\**\s*([A-Za-z ]+)", text, re.IGNORECASE)
    if rating_match:
        value = rating_match.group(1).strip().splitlines()[0]
        for action in ["Overweight", "Underweight", "Buy", "Sell", "Hold"]:
            if action.lower() in value.lower():
                return action
    for action in ["Overweight", "Underweight", "Buy", "Sell", "Hold"]:
        if re.search(rf"\b{action}\b", text, re.IGNORECASE):
            return action
    return ""

def make_offline_llm(model_key: str = "quick_think_llm"):
    """Create the configured OpenAI-compatible/LangChain LLM for offline replay."""
    if not HAS_TRADINGAGENTS:
        raise RuntimeError("TradingAgents LLM client is unavailable.")
    if HumanMessage is None or SystemMessage is None:
        raise RuntimeError("langchain_core messages are unavailable.")

    config = DEFAULT_CONFIG.copy()
    model_name = config.get(model_key) or config.get("quick_think_llm")
    logger.info(
        "Offline LLM config: provider=%s model_key=%s model=%s backend_url=%s",
        config.get("llm_provider"),
        model_key,
        model_name,
        config.get("backend_url"),
    )
    llm_kwargs = {}
    if config.get("temperature") not in (None, ""):
        llm_kwargs["temperature"] = float(config.get("temperature"))
    client = create_llm_client(
        provider=config["llm_provider"],
        model=model_name,
        base_url=config.get("backend_url"),
        **llm_kwargs,
    )
    return client.get_llm()

def invoke_offline_stage(llm, stage_name: str, system_text: str, user_text: str) -> tuple[str, int, int]:
    """Invoke one LLM stage and return content + token estimates/usage."""
    logger.info("Offline full pipeline stage: %s", stage_name)
    response = llm.invoke([SystemMessage(content=system_text), HumanMessage(content=user_text)])
    content = str(getattr(response, "content", response))
    input_tokens, output_tokens = extract_usage(response)
    if input_tokens is None:
        input_tokens = estimate_tokens(system_text + "\n" + user_text)
    if output_tokens is None:
        output_tokens = estimate_tokens(content)
    return content, input_tokens, output_tokens

def run_offline_materialized_llm(
    symbol: str,
    date: str,
    materialized_context: str,
    prompt_patch: str,
) -> tuple[dict, dict]:
    """Run one no-data-tool LLM call over already materialized point-in-time data."""
    llm = make_offline_llm()

    system_text = (
        "You are the offline historical replay market analyst for a TradingAgents tournament.\n"
        "You must use only the supplied point-in-time dataset context. Do not call tools, "
        "do not ask for external data, and do not use future knowledge.\n"
        "Return a concise but useful trading analysis with these sections:\n"
        "1. Evidence Summary\n"
        "2. Bullish Evidence\n"
        "3. Bearish Evidence\n"
        "4. Risk Notes\n"
        "5. Final Decision\n"
        "The Final Decision must contain one of: Buy, Overweight, Hold, Underweight, Sell."
    )
    user_text = (
        f"Ticker: {symbol}\n"
        f"Analysis date: {date}\n\n"
        f"{materialized_context}\n\n"
        f"{prompt_patch}\n"
    )
    content, input_tokens, output_tokens = invoke_offline_stage(
        llm,
        "single_call_decision",
        system_text,
        user_text,
    )

    final_decision = parse_offline_decision(content)
    final_state = {
        "market_report": content,
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_debate_state": {
            "bull_history": "",
            "bear_history": "",
            "history": "",
        },
        "trader_investment_plan": "",
        "risk_debate_state": {"history": ""},
        "investment_plan": content,
        "final_trade_decision": final_decision or content,
    }
    usage_info = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "llm_call_count": 1,
    }
    return final_state, usage_info

def run_offline_full_pipeline_llm(
    symbol: str,
    date: str,
    materialized_context: str,
    decision_ledger_context: str,
    memory_context: str,
    prompt_patch: str,
) -> tuple[dict, dict]:
    """Run a multi-stage offline decision workflow over materialized data.

    This mirrors the TradingAgents decision flow without live data tools:
    analyst reports -> research synthesis -> trader proposal -> risk review
    -> final portfolio decision. MeMo memory is only injected into the final
    portfolio decision stage as situational prior context.
    """
    quick_llm = make_offline_llm("quick_think_llm")
    deep_llm = make_offline_llm("deep_think_llm")
    token_in = 0
    token_out = 0
    call_count = 0

    def call(llm, stage: str, system: str, user: str) -> str:
        nonlocal token_in, token_out, call_count
        content, in_tokens, out_tokens = invoke_offline_stage(llm, stage, system, user)
        token_in += in_tokens or 0
        token_out += out_tokens or 0
        call_count += 1
        return content

    no_tools = (
        "Use only the supplied point-in-time offline context. Do not call tools, "
        "do not ask for external data, and do not use future knowledge."
    )
    base_header = f"Ticker: {symbol}\nAnalysis date: {date}\n\n"

    market_report = call(
        quick_llm,
        "market_analyst",
        f"You are the TradingAgents Market Analyst. {no_tools} Focus on price action, volume, trend, momentum, and technical risk.",
        base_header + materialized_context,
    )
    news_report = call(
        quick_llm,
        "news_social_macro_analyst",
        f"You are the TradingAgents News/Social/Macro Analyst. {no_tools} Focus on ticker news, social sentiment proxy, and macro indicators.",
        base_header + materialized_context,
    )
    fundamentals_report = call(
        quick_llm,
        "fundamentals_analyst",
        f"You are the TradingAgents Fundamentals Analyst. {no_tools} Focus on company profile, statements, earnings context, and valuation risk when present.",
        base_header + materialized_context,
    )

    research_prompt = (
        f"{base_header}"
        "Market report:\n"
        f"{market_report}\n\n"
        "News/social/macro report:\n"
        f"{news_report}\n\n"
        "Fundamentals report:\n"
        f"{fundamentals_report}\n\n"
        "Produce a balanced research-manager investment plan with bullish evidence, bearish evidence, and uncertainty."
    )
    investment_plan = call(
        quick_llm,
        "research_manager",
        f"You are the TradingAgents Research Manager. {no_tools} Synthesize analyst reports into a balanced investment plan.",
        research_prompt,
    )

    trader_prompt = (
        f"{base_header}"
        f"{decision_ledger_context}\n\n"
        "Research manager investment plan:\n"
        f"{investment_plan}\n\n"
        f"{prompt_patch}\n\n"
        "Propose a transaction plan. Explain whether to Buy, Overweight, Hold, Underweight, or Sell."
    )
    trader_plan = call(
        quick_llm,
        "trader",
        f"You are the TradingAgents Trader. {no_tools} Use the research plan and current portfolio state to propose a transaction.",
        trader_prompt,
    )

    risk_prompt = (
        f"{base_header}"
        f"{decision_ledger_context}\n\n"
        "Trader proposal:\n"
        f"{trader_plan}\n\n"
        "Analyst evidence summary:\n"
        f"Market:\n{market_report}\n\nNews/social/macro:\n{news_report}\n\nFundamentals:\n{fundamentals_report}\n\n"
        "Evaluate aggressive, neutral, and conservative risk perspectives. Identify the strongest risk-adjusted action."
    )
    risk_debate = call(
        quick_llm,
        "risk_debate",
        f"You are the TradingAgents Risk Management team. {no_tools} Stress-test the trader proposal before the final decision.",
        risk_prompt,
    )

    final_prompt = (
        f"{base_header}"
        "You are making the final portfolio decision. Memory below is prior experience only, not current market evidence.\n\n"
        f"{decision_ledger_context}\n\n"
        "Current analyst reports:\n"
        f"Market:\n{market_report}\n\nNews/social/macro:\n{news_report}\n\nFundamentals:\n{fundamentals_report}\n\n"
        "Research manager investment plan:\n"
        f"{investment_plan}\n\n"
        "Trader proposal:\n"
        f"{trader_plan}\n\n"
        "Risk review:\n"
        f"{risk_debate}\n\n"
        f"{memory_context}\n\n"
        f"{prompt_patch}\n\n"
        "Return the final decision with these sections:\n"
        "Rating: one of Buy, Overweight, Hold, Underweight, Sell\n"
        "Executive Summary:\n"
        "Investment Thesis:\n"
        "Risk Controls:\n"
    )
    final_decision_text = call(
        deep_llm,
        "portfolio_manager_final_decision",
        f"You are the TradingAgents Portfolio Manager. {no_tools} Make the final buy/sell/hold decision using current evidence first, then decision ledger, then memory as a soft prior.",
        final_prompt,
    )
    final_decision = parse_offline_decision(final_decision_text)

    final_state = {
        "market_report": market_report,
        "sentiment_report": news_report,
        "news_report": news_report,
        "fundamentals_report": fundamentals_report,
        "investment_debate_state": {
            "bull_history": investment_plan,
            "bear_history": investment_plan,
            "history": investment_plan,
        },
        "trader_investment_plan": trader_plan,
        "risk_debate_state": {"history": risk_debate},
        "investment_plan": investment_plan,
        "final_trade_decision": final_decision or final_decision_text,
    }
    usage_info = {
        "input_tokens": token_in,
        "output_tokens": token_out,
        "llm_call_count": call_count,
    }
    return final_state, usage_info

def run_mock_tradingagents(symbol: str, date: str, injected_context: str) -> dict:
    """Mock TradingAgents run for smoke testing without LLM calls."""
    logger.info(f"Running MOCK TradingAgents for {symbol} on {date}")
    time.sleep(1) # simulate work

    return {
        "company_of_interest": symbol,
        "trade_date": date,
        "market_report": "Mock market report.",
        "sentiment_report": "Mock sentiment report.",
        "news_report": "Mock news report.",
        "fundamentals_report": "Mock fundamentals report.",
        "investment_debate_state": {
            "bull_history": "...",
            "bear_history": "...",
            "history": "...",
            "current_response": "...",
            "judge_decision": "Mock bull/bear judge decision."
        },
        "trader_investment_plan": "Mock trader plan.",
        "risk_debate_state": {
            "aggressive_history": "...",
            "conservative_history": "...",
            "neutral_history": "...",
            "history": "...",
            "judge_decision": "Mock risk judge decision."
        },
        "investment_plan": "Mock final investment plan.",
        "final_trade_decision": "Buy" # Mock action
    }

def run_real_tradingagents(symbol: str, date: str, injected_context: str, selected_analysts: list[str]) -> dict:
    """Run actual TradingAgents with monkey-patched context."""
    logger.info(f"Running REAL TradingAgents for {symbol} on {date}")

    # Initialize config
    config = DEFAULT_CONFIG.copy()
    config["checkpoint_enabled"] = False # Disable checkpoint to avoid sqlite lock issues in batch
    logger.info(
        "LLM config: provider=%s quick=%s deep=%s backend_url=%s",
        config.get("llm_provider"),
        config.get("quick_think_llm"),
        config.get("deep_think_llm"),
        config.get("backend_url"),
    )

    # Init graph
    ta = TradingAgentsGraph(debug=False, config=config, selected_analysts=tuple(selected_analysts))

    # Monkey patch get_past_context to inject our tournament context
    original_get_past_context = ta.memory_log.get_past_context
    def patched_get_past_context(ticker):
        base_context = original_get_past_context(ticker)
        # Prepend our injected tournament context
        return f"{injected_context}\n\n{base_context}"

    ta.memory_log.get_past_context = patched_get_past_context

    # Run
    final_state, decision = ta.propagate(symbol, date)
    return final_state

def main():
    parser = argparse.ArgumentParser(description="Run MeMo Tournament batch.")
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--tournament-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--prompt-set-ids", nargs="+", required=True)
    parser.add_argument("--context-policy-id", default="ctx_default_v1")
    parser.add_argument("--memory-policy-id", default="mem_none_v1")
    parser.add_argument(
        "--memory-bank-version",
        default="none",
        help="Memory bank version used for this run. Use 'none' for baseline/no-memory runs.",
    )
    parser.add_argument(
        "--comparison-group",
        default=None,
        help=(
            "Optional label for before/after comparison. Defaults to "
            "baseline_no_memory when memory_policy_id is mem_none_v1, otherwise memory_enabled."
        ),
    )
    parser.add_argument(
        "--data-mode",
        choices=["tradingagents_tools", "offline_materialized", "offline_full_pipeline"],
        default="tradingagents_tools",
        help=(
            "tradingagents_tools runs the original graph/tools. offline_materialized "
            "uses one no-tool LLM call over already-crawled materialized_inputs. "
            "offline_full_pipeline uses multiple no-tool LLM calls that mirror the "
            "TradingAgents analyst/trader/risk/portfolio-manager flow."
        ),
    )
    parser.add_argument(
        "--offline-market-window-rows",
        type=int,
        default=30,
        help="Number of recent OHLCV rows to include in offline_materialized context.",
    )
    parser.add_argument(
        "--analysts",
        nargs="+",
        default=["market"],
        choices=["market", "social", "news", "fundamentals"],
        help=(
            "Analysts to run. Default is market-only to avoid live Reddit/FRED/news "
            "calls during historical tournament preflight."
        ),
    )
    parser.add_argument("--max-runs", type=int, default=250)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan the selected runs without calling TradingAgents and without writing trajectories.",
    )
    parser.add_argument("--mock", action="store_true", help="Force mock runner even if TradingAgents is installed")
    parser.add_argument(
        "--data-dir",
        default=str(THIS_DIR / "data"),
        help="Base directory containing memo_adaptation"
    )
    args = parser.parse_args()

    # Override global DATA_DIR with user arg
    global DATA_DIR
    DATA_DIR = Path(args.data_dir) / "memo_adaptation"

    logger.info(f"Starting tournament run for {args.tournament_id}")
    logger.info(f"Selected analysts: {', '.join(args.analysts)}")
    logger.info(f"Data mode: {args.data_mode}")
    comparison_group = args.comparison_group or (
        "baseline_no_memory" if args.memory_policy_id == "mem_none_v1" else "memory_enabled"
    )
    logger.info(f"Comparison group: {comparison_group}; memory bank version: {args.memory_bank_version}")

    # Load datasets
    episodes_path = DATA_DIR / "episodes" / "trading_episodes.jsonl"
    inputs_path = DATA_DIR / "materialized_inputs" / "inputs.jsonl"
    if args.context_policy_id != "ctx_default_v1":
        inputs_path = DATA_DIR / "materialized_inputs" / f"inputs_{args.context_policy_id}.jsonl"
    prompt_sets_path = DATA_DIR / "prompt_sets" / "prompt_sets.jsonl"
    trajectories_path = DATA_DIR / "trajectories" / "workflow_trajectories.jsonl"

    if not episodes_path.exists() or not inputs_path.exists() or not prompt_sets_path.exists():
        logger.error(
            "Required dataset files not found. Did you run seed builders and materializers? "
            "episodes=%s inputs=%s prompt_sets=%s",
            episodes_path.exists(),
            inputs_path.exists(),
            prompt_sets_path.exists(),
        )
        return

    episodes = load_jsonl(episodes_path)
    prompt_sets = load_jsonl(prompt_sets_path)
    existing_trajectories = load_jsonl(trajectories_path)

    # Load inputs based on context policy
    inputs = {} if args.dry_run else load_jsonl(inputs_path)

    memory_policy = {"memory_policy_id": args.memory_policy_id, "top_k_memories": 0}
    memory_records = []
    if args.memory_policy_id != "mem_none_v1" and args.memory_bank_version not in (None, "", "none"):
        memory_policy = load_memory_policy(DATA_DIR / "memory_policies" / "memory_policies.json", args.memory_policy_id)
        memory_records = load_memory_bank(DATA_DIR / "memory_bank" / "memo_memory_bank.jsonl", args.memory_bank_version)
        logger.info(
            "Loaded %d memories for memory_policy_id=%s memory_bank_version=%s",
            len(memory_records),
            args.memory_policy_id,
            args.memory_bank_version,
        )
    # Filter episodes
    selected_episodes = []
    for ep_id, ep in episodes.items():
        if ep["symbol"] in args.symbols and args.start_date <= ep["analysis_time"][:10] <= args.end_date:
            selected_episodes.append(ep)
    selected_episodes.sort(key=lambda e: (str(e.get("analysis_time", "")), str(e.get("symbol", ""))))

    logger.info(f"Found {len(selected_episodes)} episodes matching filter.")

    planned_runs = []
    for ep in selected_episodes:
        for ps_id in args.prompt_set_ids:
            if ps_id not in prompt_sets:
                continue
            traj_id = make_trajectory_id(
                args.tournament_id,
                ep["episode_id"],
                ps_id,
                args.data_mode,
                comparison_group,
                args.memory_policy_id,
                args.memory_bank_version,
            )
            would_skip_existing = (
                args.resume
                and traj_id in existing_trajectories
                and existing_trajectories[traj_id].get("run_status") == "succeeded"
            )
            planned_input_id = ep["input_id"]
            if args.context_policy_id != "ctx_default_v1":
                planned_input_id = f"{ep['symbol']}_{ep['analysis_time']}_{args.context_policy_id}"
            planned_runs.append(
                {
                    "planned_trajectory_id": traj_id,
                    "tournament_id": args.tournament_id,
                    "generation_id": args.generation_id,
                    "prompt_set_id": ps_id,
                    "episode_id": ep["episode_id"],
                    "input_id": planned_input_id,
                    "episode_input_id": ep["input_id"],
                    "symbol": ep["symbol"],
                    "analysis_time": ep["analysis_time"],
                    "context_policy_id": args.context_policy_id,
                    "memory_policy_id": args.memory_policy_id,
                    "memory_bank_version": args.memory_bank_version,
                    "comparison_group": comparison_group,
                    "would_skip_existing": would_skip_existing,
                }
            )

    if args.dry_run:
        executable_runs = [run for run in planned_runs if not run["would_skip_existing"]]
        limited_runs = executable_runs[: args.max_runs]
        dry_run_id = (
            f"dry_{args.tournament_id}_{args.generation_id}_"
            f"{args.start_date}_{args.end_date}_{pd.Timestamp.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
        )
        symbol_counts = Counter(run["symbol"] for run in executable_runs)
        prompt_counts = Counter(run["prompt_set_id"] for run in executable_runs)
        manifest = {
            "dry_run_id": dry_run_id,
            "mode": "dry_run_no_api",
            "api_required": False,
            "writes_trajectories": False,
            "generation_id": args.generation_id,
            "tournament_id": args.tournament_id,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "symbols": args.symbols,
            "prompt_set_ids": args.prompt_set_ids,
            "analysts": args.analysts,
            "data_mode": args.data_mode,
            "context_policy_id": args.context_policy_id,
            "memory_policy_id": args.memory_policy_id,
            "memory_bank_version": args.memory_bank_version,
            "comparison_group": comparison_group,
            "selected_episode_count": len(selected_episodes),
            "planned_run_count": len(planned_runs),
            "executable_run_count_after_resume": len(executable_runs),
            "limited_run_count": len(limited_runs),
            "max_runs": args.max_runs,
            "symbol_counts": dict(symbol_counts),
            "prompt_set_counts": dict(prompt_counts),
            "planned_runs_sample": limited_runs[:20],
            "created_at": pd.Timestamp.utcnow().isoformat(),
        }
        dry_run_dir = DATA_DIR / "dry_runs"
        save_json(dry_run_dir / f"{dry_run_id}.json", manifest)
        save_json(dry_run_dir / "latest_dry_run.json", manifest)
        logger.info("Dry-run mode enabled: no LLM/API calls were made and no trajectories were written.")
        logger.info(f"Planned {len(planned_runs)} runs; executable after resume: {len(executable_runs)}; max-runs limit: {args.max_runs}.")
        return

    runs_completed = 0

    use_mock = args.mock or not HAS_TRADINGAGENTS

    for ep in selected_episodes:
        if runs_completed >= args.max_runs:
            logger.info("Reached max-runs limit.")
            break

        for ps_id in args.prompt_set_ids:
            if runs_completed >= args.max_runs:
                break

            if ps_id not in prompt_sets:
                logger.warning(f"Prompt set {ps_id} not found, skipping.")
                continue

            traj_id = make_trajectory_id(
                args.tournament_id,
                ep["episode_id"],
                ps_id,
                args.data_mode,
                comparison_group,
                args.memory_policy_id,
                args.memory_bank_version,
            )

            # Check resume
            if args.resume and traj_id in existing_trajectories:
                if existing_trajectories[traj_id].get("run_status") == "succeeded":
                    logger.debug(f"Skipping already succeeded run: {traj_id}")
                    continue

            logger.info(f"Starting run {runs_completed + 1}: {traj_id}")
            start_time = time.time()

            # Prepare context. Episodes were originally built against
            # ctx_default_v1 input IDs, while policy-specific materializers
            # create IDs with the context policy suffix.
            requested_input_id = ep["input_id"]
            if args.context_policy_id != "ctx_default_v1":
                requested_input_id = f"{ep['symbol']}_{ep['analysis_time']}_{args.context_policy_id}"
            input_data = inputs.get(requested_input_id, {})

            # Use policy_id in formatting
            if args.data_mode in ("offline_materialized", "offline_full_pipeline"):
                materialized_context = format_offline_materialized_context(
                    input_data,
                    policy_id=args.context_policy_id,
                    market_window_rows=args.offline_market_window_rows,
                )
            else:
                materialized_context = format_materialized_context(input_data, args.context_policy_id)

            retrieved_memories = []
            memory_context = ""
            if memory_records:
                visible_memory_records = []
                for memory in memory_records:
                    visible_from = str(memory.get("visible_from") or memory.get("available_from") or "")
                    if visible_from and visible_from > str(ep["analysis_time"]):
                        continue
                    visible_memory_records.append(memory)
                retrieved_memories = retrieve_memories_for_context(
                    input_data=input_data,
                    symbol=ep["symbol"],
                    memories=visible_memory_records,
                    policy=memory_policy,
                )
                memory_context = format_retrieved_memories(retrieved_memories)
                if memory_context and args.data_mode != "offline_full_pipeline":
                    materialized_context = f"{materialized_context}\n\n{memory_context}"

            decision_ledger_context = ""
            current_exposure = 0.0
            decision_ledger_source_ids = []
            if args.data_mode == "offline_full_pipeline":
                decision_ledger_context, current_exposure, decision_ledger_source_ids = build_decision_ledger_context(
                    trajectories=list(existing_trajectories.values()),
                    tournament_id=args.tournament_id,
                    comparison_group=comparison_group,
                    prompt_set_id=ps_id,
                    symbol=ep["symbol"],
                    analysis_time=ep["analysis_time"],
                )

            # Prepare prompt patch
            prompt_set = prompt_sets[ps_id]
            # We inject the 'all' patch to the past_context so all agents see it.
            # In a full implementation, we would inject role-specific patches into each agent's system prompt.
            # For this pilot, appending it to the instrument/past context is a safe non-invasive way.
            patch_str = get_prompt_patch(prompt_set, "all")

            injected_context = f"{materialized_context}\n\n{patch_str}"

            error_msg = None
            final_state = {}
            status = "failed"
            usage_info = {
                "input_tokens": None,
                "output_tokens": None,
                "llm_call_count": None,
            }

            try:
                # Run agent
                # Convert analysis_time (e.g. 2022-03-01T21:00:00Z) to trade_date (2022-03-01)
                trade_date = ep["analysis_time"][:10]

                if use_mock:
                    final_state = run_mock_tradingagents(ep["symbol"], trade_date, injected_context)
                    status = "skipped"
                    error_msg = "mock_runner_debug_only_not_a_real_tournament_result"
                elif args.data_mode == "offline_materialized":
                    final_state, usage_info = run_offline_materialized_llm(
                        ep["symbol"],
                        trade_date,
                        materialized_context,
                        patch_str,
                    )
                    status = "succeeded"
                elif args.data_mode == "offline_full_pipeline":
                    final_state, usage_info = run_offline_full_pipeline_llm(
                        ep["symbol"],
                        trade_date,
                        materialized_context,
                        decision_ledger_context,
                        memory_context,
                        patch_str,
                    )
                    status = "succeeded"
                else:
                    final_state = run_real_tradingagents(
                        ep["symbol"],
                        trade_date,
                        injected_context,
                        selected_analysts=args.analysts,
                    )
                    status = "succeeded"
            except Exception as e:
                logger.error(f"Run failed: {e}")
                error_msg = str(e)

            latency = time.time() - start_time

            # Save trajectory
            trajectory = {
                "trajectory_id": traj_id,
                "tournament_id": args.tournament_id,
                "generation_id": args.generation_id,
                "prompt_set_id": ps_id,
                "episode_id": ep["episode_id"],
                "input_id": requested_input_id,
                "episode_input_id": ep["input_id"],
                "symbol": ep["symbol"],
                "analysis_time": ep["analysis_time"],
                "context_policy_id": args.context_policy_id,
                "memory_policy_id": args.memory_policy_id,
                "memory_bank_version": args.memory_bank_version,
                "retrieved_memory_ids": [m.get("memory_id") for m in retrieved_memories],
                "decision_ledger_source_ids": decision_ledger_source_ids,
                "current_exposure_before_decision": current_exposure,
                "context_windows": {
                    "market_rows_prompt": 15 if args.context_policy_id == "ctx_paper_aligned_v1" else None,
                    "technical_rows_prompt": 15 if args.context_policy_id == "ctx_paper_aligned_v1" else None,
                    "ticker_news_days": 7 if args.context_policy_id == "ctx_paper_aligned_v1" else None,
                    "ticker_news_items_prompt": 20 if args.context_policy_id == "ctx_paper_aligned_v1" else None,
                    "macro_news_days": 7 if args.context_policy_id == "ctx_paper_aligned_v1" else None,
                    "macro_news_items_prompt": 10 if args.context_policy_id == "ctx_paper_aligned_v1" else None,
                    "social_days": 7 if args.context_policy_id == "ctx_paper_aligned_v1" else None,
                    "social_items_prompt": 15 if args.context_policy_id == "ctx_paper_aligned_v1" else None,
                    "sentiment_days": 15 if args.context_policy_id == "ctx_paper_aligned_v1" else None,
                    "financial_statement_quarters": 8 if args.context_policy_id == "ctx_paper_aligned_v1" else None
                },
                "comparison_group": comparison_group,
                "data_mode": args.data_mode,
                "analysts": args.analysts,
                "agent_outputs": {
                    "market_report": final_state.get("market_report", ""),
                    "sentiment_report": final_state.get("sentiment_report", ""),
                    "news_report": final_state.get("news_report", ""),
                    "fundamentals_report": final_state.get("fundamentals_report", ""),
                    "bull_argument": final_state.get("investment_debate_state", {}).get("bull_history", ""),
                    "bear_argument": final_state.get("investment_debate_state", {}).get("bear_history", ""),
                    "investment_plan": final_state.get("investment_plan", ""),
                    "trader_plan": final_state.get("trader_investment_plan", ""),
                    "risk_debate": final_state.get("risk_debate_state", {}).get("history", ""),
                    "final_trade_decision": final_state.get("final_trade_decision", "")
                },
                "run_status": status,
                "error": error_msg,
                "input_tokens": usage_info.get("input_tokens"),
                "output_tokens": usage_info.get("output_tokens"),
                "llm_call_count": usage_info.get("llm_call_count"),
                "estimated_cost_usd": None,
                "latency_seconds": round(latency, 2),
                "created_at": pd.Timestamp.utcnow().isoformat()
            }

            upsert_jsonl(trajectories_path, "trajectory_id", trajectory)
            existing_trajectories[traj_id] = trajectory
            runs_completed += 1

    logger.info(f"Completed {runs_completed} runs.")

if __name__ == "__main__":
    main()
