"""LangChain @tool wrapper for crypto-native indicators.

Injected into the Market Analyst's tool list ONLY when asset_type == "crypto".
Stocks do not use this tool (DOM / FR / OI are meaningless for equities).
"""

from langchain_core.tools import tool
from typing import Annotated

from tradingagents.dataflows.crypto_indicators import get_crypto_native_indicators


@tool
def get_crypto_indicators(
    symbol: Annotated[str, "Crypto ticker, e.g. BTC-USD or ETH-USDT"],
    curr_date: Annotated[str, "Current analysis date, YYYY-MM-DD"],
) -> str:
    """Fetch crypto-native market indicators: Fear & Greed Index (FNG),
    Bitcoin Dominance (DOM), Perpetual Funding Rate (FR), and Open Interest (OI).
    Also evaluates long/short-squeeze risk using the composite heuristic.
    Only call this for crypto assets — it is not applicable to stocks or ETFs.
    """
    return get_crypto_native_indicators(symbol, curr_date)
