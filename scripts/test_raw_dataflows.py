"""Script to test raw data fetching from all vendors (yfinance, Reddit, StockTwits, TensorFlow).

Directly invokes the tool functions with correct parameters to verify data ingestion
integrity. This does NOT use any LLM provider, preserving your API quota.

Usage:
    python scripts/test_raw_dataflows.py
"""

import sys
import os
import time
from typing import Any, Dict

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Import tools and config
from tradingagents.dataflows.config import set_config
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


def test_raw_tool(tool_name: str, tool_fn, params: dict) -> Dict[str, Any]:
    """Invoke the tool function directly and display raw output details."""
    console.print(Panel(f"[bold cyan]Testing Raw Ingestion: {tool_name}[/bold cyan]\nParameters: {params}"))
    
    start_time = time.monotonic()
    try:
        # Check if the tool_fn is a langchain tool or raw function
        if hasattr(tool_fn, "invoke"):
            result = tool_fn.invoke(params)
        else:
            result = tool_fn(**params)
            
        elapsed = time.monotonic() - start_time
        
        # Determine status
        if not result or len(str(result).strip()) == 0:
            status = "FAIL"
            error_msg = "Returned empty data"
        elif "HTTP Error" in str(result) or "blocked" in str(result).lower():
            status = "WARNING (API Blocked)"
            error_msg = str(result)
        else:
            status = "PASS"
            error_msg = None
            
        preview = str(result)[:350] + "..." if len(str(result)) > 350 else str(result)
        console.print(Panel(preview, title=f"Ingested Result for {tool_name}", style="dim white"))
        
        return {
            "status": status,
            "time": elapsed,
            "error": error_msg,
            "length": len(str(result))
        }
    except Exception as e:
        elapsed = time.monotonic() - start_time
        console.print(f"[bold red]✕ Ingestion failed with exception: {e}[/bold red]")
        return {
            "status": "ERROR",
            "time": elapsed,
            "error": str(e),
            "length": 0
        }


def main():
    console.print(f"[bold yellow]=== CryptoAgents Raw Ingestion & Dataflow Testing (No LLM Quota) ===[/bold yellow]")
    import tradingagents
    console.print(f"[bold magenta]Package loaded from: {tradingagents.__file__}[/bold magenta]\n")

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

    tests = [
        # 1. Market Analyst
        ("get_stock_data (Stock)", get_stock_data, {"symbol": "AAPL", "start_date": "2024-11-01", "end_date": "2024-11-08"}),
        ("get_stock_data (Crypto)", get_stock_data, {"symbol": "BTC-USD", "start_date": "2024-11-01", "end_date": "2024-11-08"}),
        ("get_indicators", get_indicators, {"symbol": "AAPL", "indicator": "rsi, macd", "curr_date": "2024-11-08", "look_back_days": 7}),
        
        # 2. Sentiment Analyst (Social sources)
        ("fetch_stocktwits_messages", fetch_stocktwits_messages, {"ticker": "AAPL", "limit": 10}),
        ("fetch_reddit_posts", fetch_reddit_posts, {"ticker": "AAPL"}),
        
        # 3. News Analyst
        ("get_news (with Fallback)", get_news, {"ticker": "AAPL", "start_date": "2024-11-01", "end_date": "2024-11-08"}),
        ("get_global_news", get_global_news, {"curr_date": "2024-11-08", "look_back_days": 7, "limit": 5}),
        
        # 4. Fundamentals Analyst
        ("get_fundamentals", get_fundamentals, {"ticker": "AAPL", "curr_date": "2024-11-08"}),
        ("get_balance_sheet", get_balance_sheet, {"ticker": "AAPL", "curr_date": "2024-11-08"}),
        ("get_cashflow", get_cashflow, {"ticker": "AAPL", "curr_date": "2024-11-08"}),
        ("get_income_statement", get_income_statement, {"ticker": "AAPL", "curr_date": "2024-11-08"}),
        
        # 5. Quantitative Analyst
        ("get_anomaly_signals", get_anomaly_signals, {"symbol": "BTC-USD", "curr_date": "2024-11-08", "look_back_days": 30}),
        ("get_trend_predictions", get_trend_predictions, {"symbol": "BTC-USD", "curr_date": "2024-11-08", "look_back_days": 30}),
    ]

    results = {}
    for name, tool_fn, params in tests:
        results[name] = test_raw_tool(name, tool_fn, params)
        console.print("\n" + "-"*60 + "\n")

    # Summary
    summary_table = Table(title="Raw Data Ingestion Audit Summary")
    summary_table.add_column("Dataflow / Tool Name", justify="left", style="cyan", no_wrap=True)
    summary_table.add_column("Status", justify="center")
    summary_table.add_column("Latency", justify="right", style="magenta")
    summary_table.add_column("Data Size (Chars)", justify="right", style="green")
    summary_table.add_column("Remarks", justify="left", style="white")

    for name, res in results.items():
        status = res["status"]
        if status == "PASS":
            status_str = "[bold green]PASS[/bold green]"
        elif "WARNING" in status:
            status_str = f"[bold yellow]{status}[/bold yellow]"
        else:
            status_str = f"[bold red]{status}[/bold red]"
            
        remarks = res["error"] if res["error"] else "Data loaded successfully"
        summary_table.add_row(name, status_str, f"{res['time']:.3f}s", f"{res['length']}", remarks)

    console.print(summary_table)


if __name__ == "__main__":
    main()
