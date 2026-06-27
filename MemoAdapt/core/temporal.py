import pandas as pd
from datetime import datetime
import pytz

def get_known_time_for_daily_ohlcv(trade_date: pd.Timestamp) -> pd.Timestamp:
    """
    Theo plan: OHLCV daily thì known_time = trade_date 16:00:00 America/New_York
    """
    if trade_date.tz is not None:
        trade_date = trade_date.tz_localize(None)

    dt = datetime(trade_date.year, trade_date.month, trade_date.day, 16, 0, 0)
    ny_tz = pytz.timezone('America/New_York')
    known_time = ny_tz.localize(dt).astimezone(pytz.utc)
    return known_time

def filter_by_cutoff(df: pd.DataFrame, cutoff_time: pd.Timestamp) -> pd.DataFrame:
    """
    Loại bỏ mọi bản ghi có known_time > cutoff_time
    """
    if "known_time" not in df.columns:
        raise ValueError("DataFrame must have 'known_time' column")
    return df[df["known_time"] <= cutoff_time].copy()

def ensure_temporal_columns(df: pd.DataFrame, event_col: str, known_col: str = None, fallback_policy: str = None) -> pd.DataFrame:
    if event_col not in df.columns:
        raise ValueError(f"Column {event_col} not found in DataFrame")

    df["event_time"] = pd.to_datetime(df[event_col], utc=True)
    if known_col and known_col in df.columns:
        df["known_time"] = pd.to_datetime(df[known_col], utc=True)
    elif fallback_policy == "same_as_event":
        df["known_time"] = df["event_time"]

    return df

def get_known_time_for_news(published_at_or_date) -> pd.Timestamp:
    return pd.to_datetime(published_at_or_date, utc=True)

def get_known_time_for_statement(period_end, filing_date=None, period_type="quarterly") -> pd.Timestamp:
    if pd.notnull(filing_date):
        return pd.to_datetime(filing_date, utc=True)

    end_date = pd.to_datetime(period_end, utc=True)
    lag = pd.Timedelta(days=90) if period_type == "annual" else pd.Timedelta(days=45)
    return end_date + lag

def get_known_time_for_macro(observation_date, release_date=None, frequency="monthly") -> pd.Timestamp:
    if pd.notnull(release_date):
        return pd.to_datetime(release_date, utc=True)

    obs_date = pd.to_datetime(observation_date, utc=True)
    # Default conservative macro lag if release date is unknown
    lag = pd.Timedelta(days=30)
    return obs_date + lag
