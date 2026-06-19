from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_market_regime(
    symbol: Annotated[str, "Ticker symbol, e.g. BTC-USD, ETH-USD, AAPL"],
    curr_date: Annotated[str, "The current trading date, YYYY-MM-DD"],
    look_back_days: Annotated[int, "How many historical days to include before doubling to the HMM window"] = 60,
) -> str:
    """
    Run a TensorFlow Gaussian-HMM current market regime detector.
    The tool classifies the current regime as Bull, Bear, or Sideway from
    normalized OHLCV features. It does not forecast price.
    """
    return route_to_vendor("get_market_regime", symbol, curr_date, look_back_days)
