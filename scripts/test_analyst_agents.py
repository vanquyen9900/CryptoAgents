"""Script to test all analyst agents (Market, Sentiment, News, Fundamentals, Quantitative)

This script can run in two modes:
1. Mock Mode (default): Simulates LLM execution to verify prompt building, tool-binding, and state routing without API costs.
2. Real LLM Mode: Connects to a real provider (e.g. Google or Ollama) to test actual text and tool-calling generation.

Usage:
    # Run mock test
    python scripts/test_analyst_agents.py --provider mock

    # Run with real Google model
    GOOGLE_API_KEY=... python scripts/test_analyst_agents.py --provider google

    # Run with local Ollama model
    python scripts/test_analyst_agents.py --provider ollama
"""

import argparse
import sys
import os

# Add the project root to python path to ensure tradingagents package is resolvable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage, AIMessage

# Import analyst creation functions
from tradingagents.agents import (
    create_fundamentals_analyst,
    create_market_analyst,
    create_news_analyst,
    create_quantitative_analyst,
    create_sentiment_analyst,
)
from tradingagents.llm_clients import create_llm_client
from tradingagents.dataflows.config import set_config


class MockLLM(MagicMock):
    """Mock LLM to simulate LangChain calls and tool bindings."""
    def __init__(self, content="Mocked Analyst Report Output", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.content = content

    def bind_tools(self, tools):
        # Return self to support prompt | llm.bind_tools(...)
        return self

    def invoke(self, messages, *args, **kwargs):
        return AIMessage(content=self.content)

    def __or__(self, other):
        # Allow simple chaining if needed
        return self


def run_analyst_test(name, node, state, provider):
    print(f"\n==================================================")
    print(f" Testing: {name}")
    print(f"==================================================")
    print(f"Input State: Ticker={state.get('company_of_interest')}, Date={state.get('trade_date')}, Type={state.get('asset_type')}")
    
    try:
        # Run node
        output = node(state)
        
        # Check expected outputs
        print("\nExecution Output Keys:")
        for key in output.keys():
            print(f"  - {key}")

        # Check report content
        report_key = None
        for key in output.keys():
            if key.endswith("_report"):
                report_key = key
                break
        
        if report_key:
            report_content = output[report_key]
            print(f"\nReport Key found: '{report_key}'")
            if report_content:
                snippet = report_content[:250].replace('\n', ' ')
                print(f"Snippet: {snippet}...")
                print(f"Report Length: {len(report_content)} characters")
                print(f"Status: PASS")
                return True
            else:
                # If tool calls are generated, report might be empty on the first turn
                last_msg = output["messages"][-1]
                if hasattr(last_msg, "tool_calls") and len(last_msg.tool_calls) > 0:
                    print(f"Report is empty (Expected because LLM decided to call tools: {[tc['name'] for tc in last_msg.tool_calls]})")
                    print(f"Status: PASS (Tool Calling Triggered)")
                    return True
                else:
                    print("Status: FAIL (Report is empty and no tool calls were made)")
                    return False
        else:
            print("Status: FAIL (No report key found)")
            return False
            
    except Exception as e:
        print(f"Status: ERROR during execution: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="Test all analyst agents.")
    parser.add_argument(
        "--provider",
        choices=["mock", "google", "ollama"],
        default="mock",
        help="LLM provider to use (default: mock)"
    )
    parser.add_argument(
        "--ticker",
        default="AAPL",
        help="Ticker to use for stock analysis (default: AAPL)"
    )
    parser.add_argument(
        "--crypto-ticker",
        default="BTC-USD",
        help="Ticker to use for crypto analysis (default: BTC-USD)"
    )
    args = parser.parse_args()

    print(f"Starting analyst agents tests. Provider = {args.provider.upper()}")

    # 1. Initialize dataflow config
    set_config({
        "data_vendors": {
            "core_stock_apis": "yfinance",
            "technical_indicators": "yfinance",
            "fundamental_data": "yfinance",
            "news_data": "yfinance",
            "quantitative_analysis": "yfinance",
        }
    })

    # 2. Setup LLM client
    if args.provider == "mock":
        llm = MockLLM()
    else:
        try:
            client = create_llm_client(provider=args.provider)
            llm = client.get_llm()
            print(f"Successfully connected to real model: {args.provider}")
        except Exception as e:
            print(f"Error initializing real LLM client for {args.provider}: {e}")
            print("Please check your environment variables (.env) and try again.")
            sys.exit(1)

    # 3. Create analyst nodes
    fundamentals_node = create_fundamentals_analyst(llm)
    market_node = create_market_analyst(llm)
    news_node = create_news_analyst(llm)
    quantitative_node = create_quantitative_analyst(llm)
    sentiment_node = create_sentiment_analyst(llm)

    # 4. Run tests
    results = {}

    # Test 1: Market Analyst (Stock mode)
    stock_state = {
        "company_of_interest": args.ticker,
        "trade_date": "2024-11-01",
        "asset_type": "stock",
        "messages": [HumanMessage(content="Analyze market technicals and indicators.")],
    }
    results["Market Analyst (Stock)"] = run_analyst_test(
        "Market Analyst", market_node, stock_state, args.provider
    )

    # Test 2: News Analyst (Stock mode)
    results["News Analyst (Stock)"] = run_analyst_test(
        "News Analyst", news_node, stock_state.copy(), args.provider
    )

    # Test 3: Fundamentals Analyst (Stock mode)
    results["Fundamentals Analyst"] = run_analyst_test(
        "Fundamentals Analyst", fundamentals_node, stock_state.copy(), args.provider
    )

    # Test 4: Sentiment Analyst (Stock mode)
    results["Sentiment Analyst"] = run_analyst_test(
        "Sentiment Analyst", sentiment_node, stock_state.copy(), args.provider
    )

    # Test 5: Quantitative Analyst (Crypto mode)
    crypto_state = {
        "company_of_interest": args.crypto_ticker,
        "trade_date": "2024-11-01",
        "asset_type": "crypto",
        "messages": [HumanMessage(content="Analyze quantitative trend and anomaly indicators.")],
    }
    results["Quantitative Analyst (Crypto)"] = run_analyst_test(
        "Quantitative Analyst", quantitative_node, crypto_state, args.provider
    )

    # Print summary
    print("\n" + "=" * 50)
    print(" TEST RESULTS SUMMARY")
    print("=" * 50)
    all_passed = True
    for name, ok in results.items():
        status = "PASSED" if ok else "FAILED"
        print(f" {name:<30}: {status}")
        if not ok:
            all_passed = False
    
    print("=" * 50)
    if all_passed:
        print("All analyst agents executed successfully!")
        sys.exit(0)
    else:
        print("Some analyst agents failed to execute correctly.")
        sys.exit(1)


if __name__ == "__main__":
    main()
