from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel


class AnalystType(str, Enum):
    MARKET = "market"
    # Wire value stays "social" for saved-config and string-keyed-caller
    # back-compat; the user-facing label is "Sentiment Analyst".
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"
    # Wire value stays "quantitative" for graph compatibility; user-facing label is Regime Analyst.
    QUANTITATIVE = "quantitative"


class AssetType(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
