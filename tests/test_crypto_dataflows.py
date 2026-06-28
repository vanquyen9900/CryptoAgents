import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from tradingagents.dataflows.y_finance import (
    is_crypto_symbol,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_insider_transactions,
    get_stock_stats_indicators_window,
)
from tradingagents.dataflows.stockstats_utils import StockstatsUtils
from tradingagents.dataflows.quantitative_models import (
    preprocess_regime_features,
    run_market_regime_detection,
    get_market_regime,
)


@pytest.mark.unit
class TestCryptoDataflowBehavior:
    """Verifies crypto-specific features of the refactored dataflow module."""

    def test_is_crypto_symbol(self):
        """Verify is_crypto_symbol flags crypto pairs correctly."""
        assert is_crypto_symbol("BTC-USD") is True
        assert is_crypto_symbol("ETH-USDT") is True
        assert is_crypto_symbol("SOL-BTC") is True
        assert is_crypto_symbol("AAPL") is False
        assert is_crypto_symbol("MSFT") is False

    def test_corporate_metrics_bypassed_for_crypto(self):
        """Verify corporate metrics are bypassed when target symbol is crypto."""
        sym = "BTC-USD"
        
        res_fund = get_fundamentals(sym)
        assert "not applicable" in res_fund.lower()

        res_bs = get_balance_sheet(sym)
        assert "not applicable" in res_bs.lower()

        res_cf = get_cashflow(sym)
        assert "not applicable" in res_cf.lower()

        res_is = get_income_statement(sym)
        assert "not applicable" in res_is.lower()

        res_insider = get_insider_transactions(sym)
        assert "not applicable" in res_insider.lower()

    @patch("tradingagents.dataflows.stockstats_utils.load_ohlcv")
    def test_preceding_day_fallback(self, mock_load):
        """Verify that StockstatsUtils gets the preceding day's value if the date is missing."""
        # Create a small DataFrame with a gap (no 2026-05-26)
        dates = pd.to_datetime(["2026-05-25", "2026-05-27"])
        df = pd.DataFrame({
            "Date": dates,
            "Open": [10.0, 11.0],
            "High": [10.5, 11.5],
            "Low": [9.5, 10.5],
            "Close": [10.2, 11.2],
            "Volume": [1000, 1100],
        })
        mock_load.return_value = df

        # Request missing date: 2026-05-26
        # Expected behavior: returns value from 2026-05-25
        val = StockstatsUtils.get_stock_stats("BTC-USD", "close_10_ema", "2026-05-26")
        
        # Verify it computed something and did not return N/A string
        assert val != "N/A: Not a trading day (weekend or holiday)"
        assert isinstance(val, (int, float, str))

    @patch("tradingagents.dataflows.y_finance._get_stock_stats_bulk")
    def test_bulk_window_fallback(self, mock_bulk):
        """Verify get_stock_stats_indicators_window handles missing dates gracefully."""
        # Mock bulk dictionary with a missing date
        mock_bulk.return_value = {
            "2026-05-25": "12.5",
            "2026-05-27": "13.0"
        }

        # Request window covering 2026-05-25 to 2026-05-27
        res = get_stock_stats_indicators_window("BTC-USD", "rsi", "2026-05-27", look_back_days=2)
        
        # 2026-05-26 should fall back to 2026-05-25's value ("12.5")
        assert "2026-05-26: 12.5" in res
        assert "2026-05-27: 13.0" in res


@pytest.mark.unit
class TestTensorFlowRegimePipeline:
    """Verifies preprocessing and TensorFlow HMM regime detection."""

    def _generate_mock_ohlcv(self, length=80):
        """Helper to create fake sequential OHLCV data."""
        np.random.seed(42)
        dates = pd.date_range(start="2026-01-01", periods=length, freq="D")
        close = 100.0 + np.cumsum(np.random.normal(0, 2, length))
        df = pd.DataFrame({
            "Date": dates,
            "Open": close - np.random.uniform(0.5, 2, length),
            "High": close + np.random.uniform(0.5, 2, length),
            "Low": close - np.random.uniform(0.5, 2, length),
            "Close": close,
            "Volume": np.random.randint(1000, 5000, length).astype(float),
        })
        return df

    def test_regime_feature_engineering(self):
        """Verify regime features are engineered correctly."""
        df = self._generate_mock_ohlcv()
        processed = preprocess_regime_features(df)

        for col in [
            "log_return_1d",
            "log_return_5d",
            "volatility_20d",
            "trend_slope_20d",
            "distance_sma20",
            "drawdown_20d",
            "volume_zscore",
            "range_pct",
        ]:
            assert col in processed.columns

        assert len(processed) > 25
        assert processed.isna().sum().sum() == 0

    @patch("tradingagents.dataflows.quantitative_models.load_ohlcv")
    def test_regime_detection_runs(self, mock_load):
        """Verify TensorFlow HMM regime detection returns a structured result."""
        df = self._generate_mock_ohlcv(length=80)
        mock_load.return_value = df

        result = run_market_regime_detection("BTC-USD", "2026-03-15", look_back_days=30)

        assert result["status"] == "success"
        assert result["current_regime"] in {"Bull", "Bear", "Sideway"}
        assert 0.0 <= result["confidence"] <= 1.0
        assert len(result["recent_states"]) <= 5

    @patch("tradingagents.dataflows.quantitative_models.load_ohlcv")
    def test_market_regime_tool_report(self, mock_load):
        """Verify market regime tool returns a markdown report for agents."""
        df = self._generate_mock_ohlcv(length=80)
        mock_load.return_value = df

        report = get_market_regime("BTC-USD", "2026-03-15", look_back_days=30)

        assert "### [TensorFlow HMM Market Regime Report for BTC-USD]" in report
        assert "Current Regime" in report
        assert "Risk Condition" in report
        assert "Bull" in report or "Bear" in report or "Sideway" in report

