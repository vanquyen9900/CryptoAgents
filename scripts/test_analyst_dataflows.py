"""Script to test data fetching, API integration, and model inference for each Analyst agent.

This script executes a high-fidelity test of the five Analyst nodes by simulating the
two-turn LangGraph execution flow. This allows us to inspect:
1. The exact tool calls and parameters requested by the agents.
2. The raw data returned by those tools (yfinance, Reddit, StockTwits, TensorFlow models).
3. The exact messages history (including the raw data blocks) passed to the LLM.
4. The final generated analysis reports.

Usage:
    python scripts/test_analyst_dataflows.py --provider mock
    python scripts/test_analyst_dataflows.py --provider google
    python scripts/test_analyst_dataflows.py --provider openai
"""

import sys
import os
import argparse
import time
from typing import Any, Dict, List

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# Import tools, configurations and agents
from tradingagents.dataflows.config import set_config
from tradingagents.llm_clients import create_llm_client

# Import analyst creation factories
from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
from tradingagents.agents.analysts.quantitative_analyst import create_quantitative_analyst

# Import tools
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_news,
    get_global_news,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
)
from tradingagents.agents.utils.quantitative_analysis_tools import (
    get_anomaly_signals,
    get_trend_predictions,
)
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages

console = Console()

# Registry of tools to invoke during turn-1 tool execution simulation
TOOLS_REGISTRY = {
    "get_stock_data": get_stock_data,
    "get_indicators": get_indicators,
    "get_news": get_news,
    "get_global_news": get_global_news,
    "get_fundamentals": get_fundamentals,
    "get_balance_sheet": get_balance_sheet,
    "get_cashflow": get_cashflow,
    "get_income_statement": get_income_statement,
    "get_anomaly_signals": get_anomaly_signals,
    "get_trend_predictions": get_trend_predictions,
}


class MockAnalystLLM:
    """Custom Mock LLM for testing Analyst nodes.
    
    If the input message history only has 1 message (Turn 1):
        Returns appropriate tool calls for tool-calling agents.
    If the input message history contains ToolMessages (Turn 2):
        Returns the final analysis report.
    """
    def __init__(self, agent_type: str = "market"):
        self.agent_type = agent_type

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, *args, **kwargs):
        # Determine if we have ToolMessages in the history
        has_tool_messages = any(isinstance(m, ToolMessage) for m in messages)
        
        if not has_tool_messages:
            # Turn 1: Return appropriate tool calls based on agent type
            if self.agent_type == "market":
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_stock_data",
                            "args": {"symbol": "AAPL", "start_date": "2024-11-01", "end_date": "2024-11-08"},
                            "id": "call_m1"
                        },
                        {
                            "name": "get_indicators",
                            "args": {"symbol": "AAPL", "indicator": "rsi, macd", "curr_date": "2024-11-08"},
                            "id": "call_m2"
                        }
                    ]
                )
            elif self.agent_type == "news":
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_news",
                            "args": {"ticker": "AAPL", "start_date": "2024-11-01", "end_date": "2024-11-08"},
                            "id": "call_n1"
                        },
                        {
                            "name": "get_global_news",
                            "args": {"curr_date": "2024-11-08", "look_back_days": 7},
                            "id": "call_n2"
                        }
                    ]
                )
            elif self.agent_type == "fundamentals":
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_fundamentals",
                            "args": {"ticker": "AAPL", "curr_date": "2024-11-08"},
                            "id": "call_f1"
                        },
                        {
                            "name": "get_balance_sheet",
                            "args": {"ticker": "AAPL", "curr_date": "2024-11-08"},
                            "id": "call_f2"
                        }
                    ]
                )
            elif self.agent_type == "quantitative":
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_anomaly_signals",
                            "args": {"symbol": "BTC-USD", "curr_date": "2024-11-08"},
                            "id": "call_q1"
                        },
                        {
                            "name": "get_trend_predictions",
                            "args": {"symbol": "BTC-USD", "curr_date": "2024-11-08"},
                            "id": "call_q2"
                        }
                    ]
                )
        
        # Turn 2 (or non-tool agent like sentiment): Return final report
        return AIMessage(content=f"### [Mocked {self.agent_type.capitalize()} Analysis Report]\n\nThis is a mock report generated from the tool outputs.\n\n| Indicator | Status |\n| --- | --- |\n| Data Ingested | PASS |")

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


def simulate_agent_flow(agent_name: str, create_fn, initial_state: Dict[str, Any], provider: str, mock_type: str, report_key: str):
    """Simulate high-fidelity two-turn graph execution for an agent."""
    console.print("\n" + "="*80)
    console.print(Panel(f"[bold cyan]Simulating Agent: {agent_name}[/bold cyan]\n[bold white]Provider: {provider.upper()}[/bold white]", expand=True))
    console.print("="*80)

    # Initialize LLM
    if provider == "mock":
        llm = MockAnalystLLM(mock_type)
    else:
        from tradingagents.default_config import DEFAULT_CONFIG
        model = None
        if DEFAULT_CONFIG.get("llm_provider", "").lower() == provider:
            model = DEFAULT_CONFIG.get("deep_think_llm")
        if not model:
            defaults = {
                "google": "gemini-2.5-flash",
                "openai": "gpt-5.4",
                "ollama": "qwen3:latest"
            }
            model = defaults.get(provider, "gpt-4o")
            
        client = create_llm_client(
            provider=provider,
            model=model,
            base_url=DEFAULT_CONFIG.get("backend_url") if DEFAULT_CONFIG.get("llm_provider", "").lower() == provider else None
        )
        llm = client.get_llm()

    # Instantiate node
    node_fn = create_fn(llm)
    
    start_time = time.monotonic()
    state = initial_state.copy()
    messages = list(state["messages"])
    
    turn = 1
    max_turns = 5
    
    while turn <= max_turns:
        console.print(f"\n[bold yellow]>>> Turn {turn}: Constructing prompt & calling Agent LLM...[/bold yellow]")
        state["messages"] = messages
        output = node_fn(state)
        
        ai_msg = output["messages"][-1]
        messages.append(ai_msg)
        
        # Check for Tool Calls
        if hasattr(ai_msg, "tool_calls") and len(ai_msg.tool_calls) > 0:
            console.print(f"\n[bold green]✓ Agent requested {len(ai_msg.tool_calls)} tool calls to fetch data:[/bold green]")
            
            for tc in ai_msg.tool_calls:
                t_name = tc["name"]
                t_args = tc["args"]
                t_id = tc["id"]
                
                console.print(f"\n  • [bold blue]Executing Tool:[/bold blue] [yellow]{t_name}[/yellow]")
                console.print(f"    [dim]Parameters: {t_args}[/dim]")
                
                tool_obj = TOOLS_REGISTRY.get(t_name)
                if tool_obj:
                    try:
                        tool_output = tool_obj.invoke(t_args)
                        # Show preview of actual ingested data
                        preview_data = tool_output[:300] + "..." if len(tool_output) > 300 else tool_output
                        console.print(Panel(preview_data, title=f"Raw Ingested Data for {t_name}", style="dim white"))
                        
                        tool_msg = ToolMessage(content=tool_output, name=t_name, tool_call_id=t_id)
                        messages.append(tool_msg)
                    except Exception as e:
                        console.print(f"    [bold red]✕ Ingestion failed: {e}[/bold red]")
                        tool_msg = ToolMessage(content=f"Error executing tool: {e}", name=t_name, tool_call_id=t_id)
                        messages.append(tool_msg)
                else:
                    console.print(f"    [bold red]✕ Tool '{t_name}' not found in registry.[/bold red]")
                    tool_msg = ToolMessage(content=f"Error: Tool {t_name} not found", name=t_name, tool_call_id=t_id)
                    messages.append(tool_msg)
            turn += 1
            # Rate limit guard within multi-turn conversation
            if provider != "mock":
                time.sleep(2)
        else:
            # No tool calls: final report reached
            elapsed = time.monotonic() - start_time
            report = output.get(report_key, "")
            if not report and ai_msg.content:
                report = ai_msg.content
                
            console.print(f"\n[bold green]✓ Agent generated final report after {turn} turn(s).[/bold green]")
            console.print(Panel(report, title=f"Final Generated Report ({report_key})", style="bold green"))
            console.print(f"[bold magenta]Latency: {elapsed:.3f}s[/bold magenta]")
            return "PASS", elapsed, report

    # If max turns reached without completing
    elapsed = time.monotonic() - start_time
    console.print(f"\n[bold red]✕ Agent exceeded max turns limit ({max_turns}) without outputting final report.[/bold red]")
    return "FAIL", elapsed, "Exceeded max turns"


def main():
    parser = argparse.ArgumentParser(description="Test raw input data ingestion & node execution for each Analyst.")
    parser.add_argument(
        "--provider",
        choices=["mock", "openai", "google", "ollama"],
        default="mock",
        help="LLM provider to use (default: mock)"
    )
    parser.add_argument(
        "--agent",
        choices=["all", "market", "sentiment", "news", "fundamentals", "quantitative"],
        default="all",
        help="Specific analyst agent to test (default: all)"
    )
    args = parser.parse_args()

    console.print(f"[bold yellow]=== CryptoAgents Analyst Ingestion & Node Simulation ===[/bold yellow]")
    import tradingagents
    console.print(f"[bold magenta]Package loaded from: {tradingagents.__file__}[/bold magenta]")
    console.print(f"Testing Ingestion Integrity with Provider: {args.provider.upper()}")
    if args.agent != "all":
        console.print(f"Filtering to test agent: [cyan]{args.agent.upper()}[/cyan]\n")
    else:
        console.print("Testing all Analyst agents\n")

    # Set vendor config
    set_config({
        "data_vendors": {
            "core_stock_apis": "yfinance",
            "technical_indicators": "yfinance",
            "fundamental_data": "yfinance",
            "news_data": "yfinance",
            "quantitative_analysis": "yfinance",
        }
    })

    # Prepare states
    stock_state = {
        "company_of_interest": "AAPL",
        "trade_date": "2024-11-08",
        "asset_type": "stock",
        "messages": [HumanMessage(content="Evaluate AAPL stock data")]
    }

    crypto_state = {
        "company_of_interest": "BTC-USD",
        "trade_date": "2024-11-08",
        "asset_type": "crypto",
        "messages": [HumanMessage(content="Evaluate BTC-USD crypto data")]
    }

    simulations = [
        ("Market Analyst", create_market_analyst, stock_state, "market", "market_report"),
        ("Sentiment Analyst", create_sentiment_analyst, stock_state, "sentiment", "sentiment_report"),
        ("News Analyst", create_news_analyst, stock_state, "news", "news_report"),
        ("Fundamentals Analyst", create_fundamentals_analyst, stock_state, "fundamentals", "fundamentals_report"),
        ("Quantitative Analyst", create_quantitative_analyst, crypto_state, "quantitative", "quantitative_report"),
    ]

    if args.agent != "all":
        agent_map = {
            "market": "Market Analyst",
            "sentiment": "Sentiment Analyst",
            "news": "News Analyst",
            "fundamentals": "Fundamentals Analyst",
            "quantitative": "Quantitative Analyst"
        }
        target_name = agent_map[args.agent]
        simulations = [sim for sim in simulations if sim[0] == target_name]

    results = {}
    for name, create_fn, base_state, mock_type, report_key in simulations:
        try:
            status, elapsed, report = simulate_agent_flow(
                agent_name=name,
                create_fn=create_fn,
                initial_state=base_state.copy(),
                provider=args.provider,
                mock_type=mock_type,
                report_key=report_key
            )
            results[name] = {"status": status, "time": elapsed, "details": "Success"}
        except Exception as e:
            results[name] = {"status": "ERROR", "time": 0.0, "details": str(e)}

        # Rate limit guard between different agent runs
        if args.provider != "mock" and name != simulations[-1][0]:
            console.print("[dim]Sleeping 10s to respect LLM rate limits...[/dim]")
            time.sleep(10)

    # Summary Table
    console.print("\n" + "="*80)
    console.print("[bold green]=== INGESTION & SIMULATION RESULTS SUMMARY ===[/bold green]")
    console.print("="*80)
    
    summary_table = Table(title="High-Fidelity Agent Ingestion Simulation")
    summary_table.add_column("Agent Name", justify="left", style="cyan", no_wrap=True)
    summary_table.add_column("Status", justify="center", style="bold green")
    summary_table.add_column("Total Latency (s)", justify="right", style="magenta")
    summary_table.add_column("Details", justify="left", style="white")

    for name, res in results.items():
        status_str = f"[bold green]{res['status']}[/bold green]" if res["status"] == "PASS" else f"[bold red]{res['status']}[/bold red]"
        summary_table.add_row(name, status_str, f"{res['time']:.3f}s", res["details"])
        
    console.print(summary_table)


if __name__ == "__main__":
    main()
