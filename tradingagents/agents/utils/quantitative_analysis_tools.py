from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_anomaly_signals(
    symbol: Annotated[str, "Ticker symbol of the cryptocurrency, e.g. BTC-USD, ETH-USD"],
    curr_date: Annotated[str, "The current trading date, YYYY-MM-DD"],
    look_back_days: Annotated[int, "How many historical days to include in the analysis"] = 60,
) -> str:
    """
    Run TensorFlow Autoencoder Anomaly Detection on the given crypto asset.
    Detects abnormal price movements, flash crashes, pump-and-dump patterns,
    or abnormal trading volumes using deep learning reconstruction error.

    Args:
        symbol (str): Ticker symbol of the cryptocurrency, e.g. BTC-USD
        curr_date (str): The current trading date, YYYY-MM-DD
        look_back_days (int): How many historical days to analyze (default 60)
    Returns:
        str: Markdown report with anomaly score, threshold, and flagged dates
    """
    return route_to_vendor("get_anomaly_signals", symbol, curr_date, look_back_days)


@tool
def get_trend_predictions(
    symbol: Annotated[str, "Ticker symbol of the cryptocurrency, e.g. BTC-USD, ETH-USD"],
    curr_date: Annotated[str, "The current trading date, YYYY-MM-DD"],
    look_back_days: Annotated[int, "How many historical days to train the forecast model on"] = 60,
) -> str:
    """
    Run TensorFlow LSTM Price Trend Forecasting for a crypto asset.
    Predicts the short-term price direction (UP, DOWN, HOLD) over the next
    3 trading periods with confidence probabilities.

    Args:
        symbol (str): Ticker symbol of the cryptocurrency, e.g. BTC-USD
        curr_date (str): The current trading date, YYYY-MM-DD
        look_back_days (int): How many historical days to use for training (default 60)
    Returns:
        str: Markdown report with predicted direction and confidence percentages
    """
    return route_to_vendor("get_trend_predictions", symbol, curr_date, look_back_days)
