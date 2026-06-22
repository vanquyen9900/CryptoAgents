"""Script to test every single agent in the CryptoAgents framework.

Tests the following agents:
1. Market Analyst (Stock & Crypto)
2. Sentiment Analyst (Stock & Crypto)
3. News Analyst (Stock & Crypto)
4. Fundamentals Analyst (Stock only)
5. Quantitative Analyst (Crypto only)
6. Bull Researcher (Research debate team)
7. Bear Researcher (Research debate team)
8. Research Manager (Synthesis and structured output)
9. Trader (Transaction proposal)
10. Aggressive Analyst (Risk debate team)
11. Conservative Analyst (Risk debate team)
12. Neutral Analyst (Risk debate team)
13. Portfolio Manager (Final decision and structured output)

Usage:
    # Run in mock mode (fast, free, tests system integration and schemas)
    python scripts/test_all_agents.py --provider mock

    # Run with a real LLM provider (tests actual generation and API compatibility)
    python scripts/test_all_agents.py --provider google
    python scripts/test_all_agents.py --provider openai
    python scripts/test_all_agents.py --provider ollama
"""

import argparse
import sys
import os
import time
from typing import Dict, Any

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from langchain_core.messages import HumanMessage, AIMessage

# Import schemas and agents
from tradingagents.agents.schemas import (
    ResearchPlan, PortfolioRating, TraderProposal, TraderAction, PortfolioDecision
)
from tradingagents.agents import (
    create_market_analyst,
    create_sentiment_analyst,
    create_news_analyst,
    create_fundamentals_analyst,
    create_quantitative_analyst,
    create_bull_researcher,
    create_bear_researcher,
    create_research_manager,
    create_trader,
    create_aggressive_debator,
    create_conservative_debator,
    create_neutral_debator,
    create_portfolio_manager,
)
from tradingagents.llm_clients import create_llm_client
from tradingagents.dataflows.config import set_config

console = Console()

class MockStructuredLLM:
    """Mock LLM that can handle structured outputs and normal completions."""
    def __init__(self, schema=None, content=None):
        self.schema = schema
        self.content = content or "Mocked agent completion text."

    def with_structured_output(self, schema):
        return MockStructuredLLM(schema=schema)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, *args, **kwargs):
        if self.schema == ResearchPlan:
            return ResearchPlan(
                recommendation=PortfolioRating.BUY,
                rationale="Mocked buy rationale: technicals indicate strong volume support.",
                strategic_actions="Mocked strategic actions: buy 50% allocation, stop-loss at 5% below entry."
            )
        elif self.schema == TraderProposal:
            return TraderProposal(
                action=TraderAction.BUY,
                reasoning="Mocked trading reasoning based on buy recommendation.",
                entry_price=100.0,
                stop_loss=95.0,
                position_sizing="5% of portfolio"
            )
        elif self.schema == PortfolioDecision:
            return PortfolioDecision(
                rating=PortfolioRating.BUY,
                executive_summary="Mocked executive summary: execute buy order at market open.",
                investment_thesis="Mocked investment thesis: strong volume, bullish trend, and low risk.",
                price_target=110.0,
                time_horizon="1 month"
            )
        else:
            return AIMessage(content=self.content)

    def __call__(self, messages, *args, **kwargs):
        if hasattr(messages, "to_messages"):
            messages = messages.to_messages()
        return self.invoke(messages, *args, **kwargs)

    def __or__(self, other):
        from langchain_core.runnables import RunnableSequence, coerce_to_runnable
        return RunnableSequence(first=coerce_to_runnable(self), last=coerce_to_runnable(other))

    def __ror__(self, other):
        from langchain_core.runnables import RunnableSequence, coerce_to_runnable
        return RunnableSequence(first=coerce_to_runnable(other), last=coerce_to_runnable(self))


def run_agent_test(name: str, node_func, state: Dict[str, Any], expected_key: str, required_markers: list) -> Dict[str, Any]:
    console.print(Panel(f"[bold cyan]Testing Agent: {name}[/bold cyan]"))
    
    start_time = time.monotonic()
    try:
        output = node_func(state)
        elapsed = time.monotonic() - start_time
        
        # 1. Output key presence validation
        if expected_key not in output:
            return {
                "status": "FAIL",
                "time": elapsed,
                "error": f"Missing expected state key: '{expected_key}'",
                "markers_checked": 0,
                "markers_passed": 0
            }
            
        report = output[expected_key]
        
        # If the result of the first turn is empty because the model decided to call tools (e.g. Market Analyst)
        if not report and "messages" in output:
            last_msg = output["messages"][-1]
            if hasattr(last_msg, "tool_calls") and len(last_msg.tool_calls) > 0:
                tool_names = [tc["name"] for tc in last_msg.tool_calls]
                return {
                    "status": "PASS (Tools Called)",
                    "time": elapsed,
                    "details": f"Triggered tool calls: {tool_names}",
                    "markers_checked": 0,
                    "markers_passed": 0
                }
        
        # Convert structured type to string for formatting checks
        report_str = str(report)
        
        # 2. Metric Evaluation: Compliance with markdown headers / markers
        markers_passed = 0
        failed_markers = []
        for marker in required_markers:
            if marker in report_str:
                markers_passed += 1
            else:
                failed_markers.append(marker)
                
        # 3. Response completeness (length metric)
        min_len = 10
        if len(report_str) < min_len:
            return {
                "status": "FAIL",
                "time": elapsed,
                "error": f"Response is too short ({len(report_str)} chars).",
                "markers_checked": len(required_markers),
                "markers_passed": markers_passed
            }
            
        status = "PASS" if markers_passed == len(required_markers) else "WARNING"
        details = ""
        if failed_markers:
            details = f"Missing markers: {failed_markers}"
            
        return {
            "status": status,
            "time": elapsed,
            "details": details,
            "markers_checked": len(required_markers),
            "markers_passed": markers_passed
        }
        
    except Exception as e:
        elapsed = time.monotonic() - start_time
        return {
            "status": "ERROR",
            "time": elapsed,
            "error": str(e),
            "markers_checked": len(required_markers),
            "markers_passed": 0
        }


def main():
    parser = argparse.ArgumentParser(description="Run evaluation tests on all agents.")
    parser.add_argument(
        "--provider",
        choices=["mock", "openai", "google", "ollama"],
        default="mock",
        help="LLM provider to test (default: mock)"
    )
    args = parser.parse_args()

    console.print(f"[bold yellow]=== CryptoAgents Comprehensive Agent Testing ===[/bold yellow]")
    console.print(f"Testing Environment: Provider = {args.provider.upper()}\n")

    # Initialize dataflow config
    set_config({
        "data_vendors": {
            "core_stock_apis": "yfinance",
            "technical_indicators": "yfinance",
            "fundamental_data": "yfinance",
            "news_data": "yfinance",
            "quantitative_analysis": "yfinance",
        }
    })

    # Initialize LLM
    if args.provider == "mock":
        llm = MockStructuredLLM()
    else:
        from tradingagents.default_config import DEFAULT_CONFIG
        
        provider = args.provider.lower()
        model = None
        
        # If the configured provider matches the target provider, use configured model
        if DEFAULT_CONFIG.get("llm_provider", "").lower() == provider:
            model = DEFAULT_CONFIG.get("deep_think_llm")
            
        if not model:
            # Fallback defaults for testing
            defaults = {
                "google": "gemini-2.5-flash",
                "openai": "gpt-5.4",
                "ollama": "qwen3:latest"
            }
            model = defaults.get(provider, "gpt-4o")
            
        try:
            client = create_llm_client(
                provider=provider,
                model=model,
                base_url=DEFAULT_CONFIG.get("backend_url") if DEFAULT_CONFIG.get("llm_provider", "").lower() == provider else None
            )
            llm = client.get_llm()
            console.print(f"[green]Successfully initialized real LLM client for {provider} using model {model}[/green]")
        except Exception as e:
            console.print(f"[bold red]Failed to initialize LLM client: {e}[/bold red]")
            sys.exit(1)

    # Instantiate all agents
    market_node = create_market_analyst(llm)
    sentiment_node = create_sentiment_analyst(llm)
    news_node = create_news_analyst(llm)
    fundamentals_node = create_fundamentals_analyst(llm)
    quantitative_node = create_quantitative_analyst(llm)
    bull_node = create_bull_researcher(llm)
    bear_node = create_bear_researcher(llm)
    manager_node = create_research_manager(llm)
    trader_node = create_trader(llm)
    aggressive_node = create_aggressive_debator(llm)
    conservative_node = create_conservative_debator(llm)
    neutral_node = create_neutral_debator(llm)
    portfolio_node = create_portfolio_manager(llm)

    test_results = {}

    # Define base states
    stock_state = {
        "company_of_interest": "AAPL",
        "trade_date": "2024-11-01",
        "asset_type": "stock",
        "messages": [HumanMessage(content="Start stock evaluation")],
        "market_report": "Mocked technical indicators table shows oversold RSI.",
        "sentiment_report": "Mocked news feeds show extremely positive analyst ratings.",
        "news_report": "Mocked corporate announcements show earnings beat.",
        "fundamentals_report": "Mocked balance sheet details strong cash positions.",
        "investment_debate_state": {
            "count": 2,
            "history": "Bull: Market looks bullish.\nBear: Volatility is high.",
            "bear_history": "Volatility is high.",
            "bull_history": "Market looks bullish.",
            "current_response": "Bear: Volatility is high."
        },
        "investment_plan": "**Recommendation**: Buy\n**Rationale**: Technicals look good.",
        "trader_investment_plan": "**Action**: Buy\n**Reasoning**: Strategic momentum.",
        "risk_debate_state": {
            "count": 3,
            "history": "Aggressive: Leverage up.\nConservative: Hedging required.\nNeutral: Follow limits.",
            "aggressive_history": "Leverage up.",
            "conservative_history": "Hedging required.",
            "neutral_history": "Follow limits.",
            "latest_speaker": "Neutral",
            "current_aggressive_response": "Leverage up.",
            "current_conservative_response": "Hedging required.",
            "current_neutral_response": "Follow limits."
        }
    }

    crypto_state = stock_state.copy()
    crypto_state.update({
        "company_of_interest": "BTC-USD",
        "asset_type": "crypto",
        "quantitative_report": "Mocked LSTM forecast indicates UP trend with 85% confidence."
    })

    # --- Phase 1: Analyst Node Tests ---
    
    # 1. Market Analyst
    test_results["1. Market Analyst"] = run_agent_test(
        "Market Analyst", market_node, stock_state.copy(), "market_report", []
    )
    
    # 2. Sentiment Analyst
    test_results["2. Sentiment Analyst"] = run_agent_test(
        "Sentiment Analyst", sentiment_node, stock_state.copy(), "sentiment_report", []
    )

    # 3. News Analyst
    test_results["3. News Analyst"] = run_agent_test(
        "News Analyst", news_node, stock_state.copy(), "news_report", []
    )

    # 4. Fundamentals Analyst
    test_results["4. Fundamentals Analyst"] = run_agent_test(
        "Fundamentals Analyst", fundamentals_node, stock_state.copy(), "fundamentals_report", []
    )

    # 5. Quantitative Analyst
    test_results["5. Quantitative Analyst"] = run_agent_test(
        "Quantitative Analyst", quantitative_node, crypto_state.copy(), "quantitative_report", []
    )

    # --- Phase 2: Researcher Node Tests ---

    # 6. Bull Researcher
    # Bull researcher returns updated debate state history
    test_results["6. Bull Researcher"] = run_agent_test(
        "Bull Researcher", bull_node, crypto_state.copy(), "investment_debate_state", []
    )

    # 7. Bear Researcher
    test_results["7. Bear Researcher"] = run_agent_test(
        "Bear Researcher", bear_node, crypto_state.copy(), "investment_debate_state", []
    )

    # --- Phase 3: Manager and Trading Nodes ---

    # 8. Research Manager
    # Research Manager produces markdown formatted structured output
    test_results["8. Research Manager"] = run_agent_test(
        "Research Manager", manager_node, crypto_state.copy(), "investment_plan", 
        ["**Recommendation**", "**Rationale**", "**Strategic Actions**"]
    )

    # 9. Trader
    # Trader produces transaction action and reasoning
    test_results["9. Trader"] = run_agent_test(
        "Trader", trader_node, crypto_state.copy(), "trader_investment_plan",
        ["**Action**", "**Reasoning**", "FINAL TRANSACTION PROPOSAL"]
    )

    # --- Phase 4: Risk and Portfolio Nodes ---

    # 10. Aggressive Analyst
    test_results["10. Aggressive Analyst"] = run_agent_test(
        "Aggressive Analyst", aggressive_node, crypto_state.copy(), "risk_debate_state", []
    )

    # 11. Conservative Analyst
    test_results["11. Conservative Analyst"] = run_agent_test(
        "Conservative Analyst", conservative_node, crypto_state.copy(), "risk_debate_state", []
    )

    # 12. Neutral Analyst
    test_results["12. Neutral Analyst"] = run_agent_test(
        "Neutral Analyst", neutral_node, crypto_state.copy(), "risk_debate_state", []
    )

    # 13. Portfolio Manager
    # Portfolio Manager produces final decision with Rating, Summary, and Thesis
    test_results["13. Portfolio Manager"] = run_agent_test(
        "Portfolio Manager", portfolio_node, crypto_state.copy(), "final_trade_decision",
        ["**Rating**", "**Executive Summary**", "**Investment Thesis**"]
    )

    # --- Print Evaluation Summary Table ---
    console.print("\n" + "="*70)
    console.print("[bold green]=== AGENT EVALUATION METRIC SUMMARY ===[/bold green]")
    console.print("="*70)

    summary_table = Table(title="Agent Performance & Metric Validation")
    summary_table.add_column("Agent Name", justify="left", style="cyan", no_wrap=True)
    summary_table.add_column("Status", justify="center", style="bold green")
    summary_table.add_column("Latency (s)", justify="right", style="magenta")
    summary_table.add_column("Compliance (Passed/Checked)", justify="center", style="yellow")
    summary_table.add_column("Remarks / Fallbacks / Warnings", justify="left", style="white")

    all_passed = True
    for name, metrics in test_results.items():
        status = metrics["status"]
        if "FAIL" in status or "ERROR" in status:
            status_str = f"[bold red]{status}[/bold red]"
            all_passed = False
        elif "WARNING" in status:
            status_str = f"[bold yellow]{status}[/bold yellow]"
            all_passed = False
        else:
            status_str = f"[bold green]{status}[/bold green]"

        time_str = f"{metrics['time']:.3f}s"
        
        checked = metrics.get("markers_checked", 0)
        passed = metrics.get("markers_passed", 0)
        compliance_str = f"{passed}/{checked}" if checked > 0 else "N/A"
        
        remarks = metrics.get("details", "") or metrics.get("error", "") or "No warnings"
        
        summary_table.add_row(name, status_str, time_str, compliance_str, remarks)

    console.print(summary_table)
    console.print("="*70)

    if all_passed:
        console.print("[bold green]All 13 agents successfully passed evaluation tests![/bold green]")
        sys.exit(0)
    else:
        console.print("[bold red]Some agents failed key metrics or returned formatting warnings.[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
