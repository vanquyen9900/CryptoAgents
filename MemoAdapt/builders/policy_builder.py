import os
import sys
import json
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.storage import DATA_DIR

def build_policies():
    print("Building Context, Memory, and Prompt Policies (Phases 3-5)...")

    # Context Policies
    ctx_dir = DATA_DIR / "memo_adaptation" / "context_policies"
    ctx_dir.mkdir(parents=True, exist_ok=True)

    context_policies = [
        {
            "context_policy_id": "ctx_default_v1",
            "description": "Balanced default context pack",
            "market_window_days": 90,
            "technical_indicators": ["close_10_ema", "close_50_sma", "close_200_sma", "rsi_14", "macd", "macd_signal", "macd_hist", "atr_14"],
            "fundamentals_quarters": 8,
            "max_ticker_news": 20,
            "max_macro_news": 10,
            "max_social_items": 30
        },
        {
            "context_policy_id": "ctx_short_market_v1",
            "description": "Shorter market context for recent momentum",
            "market_window_days": 45,
            "technical_indicators": ["close_10_ema", "close_50_sma", "rsi_14", "macd", "atr_14"],
            "fundamentals_quarters": 4,
            "max_ticker_news": 10,
            "max_macro_news": 5,
            "max_social_items": 15
        },
        {
            "context_policy_id": "ctx_long_market_v1",
            "description": "Longer market context for trend and regime",
            "market_window_days": 180,
            "technical_indicators": ["close_10_ema", "close_50_sma", "close_200_sma", "rsi_14", "macd", "macd_signal", "macd_hist", "boll_upper", "boll_mid", "boll_lower", "atr_14"],
            "fundamentals_quarters": 8,
            "max_ticker_news": 30,
            "max_macro_news": 15,
            "max_social_items": 40
        },
        {
            "context_policy_id": "ctx_paper_aligned_v1",
            "description": "Paper-aligned compact context pack for offline MeMo tournaments",
            "market_window_days": 90,
            "market_window_trading_rows": 15,
            "technical_window_trading_rows": 15,
            "technical_indicators": ["close_10_ema", "close_50_sma", "close_200_sma", "rsi_14", "macd", "macd_signal", "macd_hist", "boll_mid", "boll_upper", "boll_lower", "atr_14"],
            "financial_statement_quarters": 8,
            "fundamentals_quarters": 8,
            "ticker_news_window_days": 7,
            "ticker_news_max_materialized": 20,
            "macro_news_window_days": 7,
            "macro_news_max_materialized": 10,
            "social_window_days": 7,
            "social_max_materialized": 15,
            "sentiment_window_days": 7,
            "sentiment_max_materialized": 15,
            "max_ticker_news": 20,
            "max_macro_news": 10,
            "max_social_items": 15
        }
    ]

    with open(ctx_dir / "context_policies.json", "w", encoding="utf-8") as f:
        json.dump(context_policies, f, indent=2)

    # Memory Policies
    mem_dir = DATA_DIR / "memo_adaptation" / "memory_policies"
    mem_dir.mkdir(parents=True, exist_ok=True)

    memory_policies = [
        {
            "memory_policy_id": "mem_none_v1",
            "description": "No MeMo memory, baseline",
            "top_k_memories": 0,
            "same_symbol_boost": False,
            "same_regime_required": False,
            "agent_role_filter": True
        },
        {
            "memory_policy_id": "mem_top5_role_v1",
            "description": "Retrieve top 5 memories for same agent role",
            "top_k_memories": 5,
            "same_symbol_boost": True,
            "same_regime_required": False,
            "agent_role_filter": True
        },
        {
            "memory_policy_id": "mem_top3_regime_v1",
            "description": "Retrieve top 3 memories with stricter regime matching",
            "top_k_memories": 3,
            "same_symbol_boost": True,
            "same_regime_required": True,
            "agent_role_filter": True
        }
    ]

    with open(mem_dir / "memory_policies.json", "w", encoding="utf-8") as f:
        json.dump(memory_policies, f, indent=2)

    # Prompt Variants
    prompt_dir = DATA_DIR / "memo_adaptation" / "prompt_variants"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    prompt_variants = [
        {
            "prompt_variant_id": "prompt_default_v1",
            "agent_role": "all",
            "base_prompt_id": "tradingagents_default",
            "variant_type": "baseline",
            "instruction_patch": ""
        },
        {
            "prompt_variant_id": "prompt_evidence_based_v1",
            "agent_role": "all",
            "base_prompt_id": "tradingagents_default",
            "variant_type": "instruction_patch",
            "instruction_patch": "Prefer evidence-backed conclusions. Separate facts, assumptions, and uncertainty."
        },
        {
            "prompt_variant_id": "prompt_risk_aware_v1",
            "agent_role": "trader",
            "base_prompt_id": "tradingagents_default_trader",
            "variant_type": "instruction_patch",
            "instruction_patch": "Make risk-adjusted reasoning explicit. Do not ignore downside scenarios."
        },
        {
            "prompt_variant_id": "prompt_memory_aware_v1",
            "agent_role": "all",
            "base_prompt_id": "tradingagents_default",
            "variant_type": "instruction_patch",
            "instruction_patch": "Use retrieved historical lessons only when they are relevant to the current evidence. Do not treat memory as ground truth."
        }
    ]

    with open(prompt_dir / "prompt_variants.json", "w", encoding="utf-8") as f:
        json.dump(prompt_variants, f, indent=2)

    print("Policies generated successfully.")

if __name__ == "__main__":
    build_policies()
