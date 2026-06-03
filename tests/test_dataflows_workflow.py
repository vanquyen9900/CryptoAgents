"""Tests for the complete dataflow and routing workflow.

This suite validates the core data-fetching pipeline:
1. Vendor routing based on active configuration (category level vs. tool level).
2. Fallback logic: recovering from Alpha Vantage rate limit errors by failing over to Yahoo Finance.
3. Proper exception propagation on non-rate-limit failures.
4. Correctness of category lookup for all supported analytical tools.
"""

import copy
import pytest
from unittest.mock import MagicMock, patch

from tradingagents.dataflows.interface import (
    route_to_vendor,
    get_category_for_method,
    get_vendor,
    VENDOR_METHODS,
    TOOLS_CATEGORIES,
)
import tradingagents.dataflows.config as df_config
from tradingagents.dataflows.config import get_config, set_config
from tradingagents.dataflows.alpha_vantage_common import AlphaVantageRateLimitError
import tradingagents.default_config as default_config


@pytest.fixture(autouse=True)
def isolated_dataflow_config():
    """Ensure that config changes made during tests do not bleed into other tests."""
    # Since set_config does in-place dictionary updates/merges, calling set_config
    # with the original config does not delete newly added keys (like tool_vendors overrides).
    # We must do a deepcopy and reassign df_config._config directly to fully isolate the tests.
    original_config = copy.deepcopy(df_config._config)
    yield
    df_config._config = original_config


@pytest.mark.unit
class TestDataflowsWorkflowRouting:
    """Validates category configuration routing, overrides, and error fallbacks."""

    def test_get_category_for_method(self):
        """Verify that every recognized tool maps to its proper data category."""
        assert get_category_for_method("get_stock_data") == "core_stock_apis"
        assert get_category_for_method("get_indicators") == "technical_indicators"
        assert get_category_for_method("get_fundamentals") == "fundamental_data"
        assert get_category_for_method("get_news") == "news_data"

        with pytest.raises(ValueError, match="Method 'invalid_method' not found"):
            get_category_for_method("invalid_method")

    def test_default_routing_resolves_to_yfinance(self):
        """By default, most data categories route to Yahoo Finance."""
        assert get_vendor("core_stock_apis") == "yfinance"
        assert get_vendor("technical_indicators") == "yfinance"
        assert get_vendor("fundamental_data") == "yfinance"
        assert get_vendor("news_data") == "yfinance"

    def test_config_override_routes_to_alpha_vantage(self):
        """Setting category-level vendor shifts routing target accordingly."""
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})
        assert get_vendor("core_stock_apis") == "alpha_vantage"

        # Other categories remain unaffected
        assert get_vendor("news_data") == "yfinance"

    def test_tool_level_override_takes_precedence(self):
        """Tool-level override must override category defaults."""
        set_config({
            "data_vendors": {"news_data": "yfinance"},
            "tool_vendors": {"get_news": "alpha_vantage"}
        })
        
        # Category remains yfinance
        assert get_vendor("news_data") == "yfinance"
        # Specifically get_news routes to alpha_vantage
        assert get_vendor("news_data", method="get_news") == "alpha_vantage"
        # Other tools in the same category still use category default
        assert get_vendor("news_data", method="get_global_news") == "yfinance"

    def test_route_to_vendor_calls_primary_yfinance(self):
        """Verifies route_to_vendor correctly forwards args and returns value from yfinance."""
        set_config({"data_vendors": {"core_stock_apis": "yfinance"}})

        mock_yfinance = MagicMock(return_value="yfinance_stock_data")
        mock_alpha_vantage = MagicMock(return_value="alpha_vantage_stock_data")

        with patch.dict(VENDOR_METHODS["get_stock_data"], {
            "yfinance": mock_yfinance,
            "alpha_vantage": mock_alpha_vantage
        }):
            result = route_to_vendor("get_stock_data", "AAPL", "2024-11-01", "2024-11-30")
            
            assert result == "yfinance_stock_data"
            mock_yfinance.assert_called_once_with("AAPL", "2024-11-01", "2024-11-30")
            mock_alpha_vantage.assert_not_called()

    def test_route_to_vendor_calls_primary_alpha_vantage(self):
        """Verifies route_to_vendor shifts to alpha_vantage when configured."""
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})

        mock_yfinance = MagicMock(return_value="yfinance_stock_data")
        mock_alpha_vantage = MagicMock(return_value="alpha_vantage_stock_data")

        with patch.dict(VENDOR_METHODS["get_stock_data"], {
            "yfinance": mock_yfinance,
            "alpha_vantage": mock_alpha_vantage
        }):
            result = route_to_vendor("get_stock_data", "AAPL", "2024-11-01", "2024-11-30")
            
            assert result == "alpha_vantage_stock_data"
            mock_alpha_vantage.assert_called_once_with("AAPL", "2024-11-01", "2024-11-30")
            mock_yfinance.assert_not_called()

    def test_fallback_mechanism_on_alpha_vantage_rate_limit(self):
        """AlphaVantageRateLimitError should trigger automatic fallback to yfinance."""
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})

        mock_yfinance = MagicMock(return_value="fallback_yfinance_data")
        
        # Primary vendor throws rate limit error
        mock_alpha_vantage = MagicMock(side_effect=AlphaVantageRateLimitError("Rate limit exceeded"))

        with patch.dict(VENDOR_METHODS["get_stock_data"], {
            "yfinance": mock_yfinance,
            "alpha_vantage": mock_alpha_vantage
        }):
            result = route_to_vendor("get_stock_data", "AAPL", "2024-11-01", "2024-11-30")
            
            # The workflow should intercept the error and return the fallback vendor's output
            assert result == "fallback_yfinance_data"
            mock_alpha_vantage.assert_called_once_with("AAPL", "2024-11-01", "2024-11-30")
            mock_yfinance.assert_called_once_with("AAPL", "2024-11-01", "2024-11-30")

    def test_no_fallback_on_unrelated_errors(self):
        """Generic exceptions raised by the primary vendor must propagate immediately."""
        set_config({"data_vendors": {"core_stock_apis": "alpha_vantage"}})

        mock_yfinance = MagicMock(return_value="fallback_yfinance_data")
        mock_alpha_vantage = MagicMock(side_effect=ValueError("Invalid ticker symbol format"))

        with patch.dict(VENDOR_METHODS["get_stock_data"], {
            "yfinance": mock_yfinance,
            "alpha_vantage": mock_alpha_vantage
        }):
            # Value error should propagate without triggering the fallback chain
            with pytest.raises(ValueError, match="Invalid ticker symbol format"):
                route_to_vendor("get_stock_data", "AAPL", "2024-11-01", "2024-11-30")
            
            mock_alpha_vantage.assert_called_once()
            mock_yfinance.assert_not_called()

    def test_unsupported_routing_method_raises_value_error(self):
        """Methods that are not in VENDOR_METHODS should fail gracefully."""
        patched_categories = copy.deepcopy(TOOLS_CATEGORIES)
        patched_categories["core_stock_apis"]["tools"].append("unknown_method")

        with patch.dict(TOOLS_CATEGORIES, patched_categories):
            with pytest.raises(ValueError, match="Method 'unknown_method' not supported"):
                route_to_vendor("unknown_method")


@pytest.mark.unit
class TestDataflowsWorkflowEndToEnd:
    """Verifies that all standard project analytical tools route successfully through the categories."""

    def test_all_tools_resolve_in_vendor_methods(self):
        """Ensure all tools defined in the main configuration exist in the VENDOR_METHODS lookup."""
        for category, info in TOOLS_CATEGORIES.items():
            for tool_name in info["tools"]:
                assert tool_name in VENDOR_METHODS, f"Method '{tool_name}' missing from VENDOR_METHODS."
                
                # Verify that yfinance is configured for each tool in VENDOR_METHODS
                assert "yfinance" in VENDOR_METHODS[tool_name], f"yfinance missing for {tool_name}."
                # Verify that alpha_vantage is configured for each tool in VENDOR_METHODS
                assert "alpha_vantage" in VENDOR_METHODS[tool_name], f"alpha_vantage missing for {tool_name}."

    def test_routing_flow_for_fundamental_tools(self):
        """Validate routing works correctly for all fundamental statement APIs."""
        fundamental_tools = ["get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"]
        
        for tool_name in fundamental_tools:
            mock_yfinance = MagicMock(return_value=f"yfinance_{tool_name}_data")
            
            with patch.dict(VENDOR_METHODS[tool_name], {"yfinance": mock_yfinance}):
                # Force yfinance for consistency
                set_config({"data_vendors": {"fundamental_data": "yfinance"}})
                result = route_to_vendor(tool_name, "AAPL", "2024-11-01")
                assert result == f"yfinance_{tool_name}_data"
                mock_yfinance.assert_called_once()

    def test_routing_flow_for_news_tools(self):
        """Validate routing works correctly for all news and transactional APIs."""
        news_tools = {
            "get_news": ("AAPL", "2024-11-01", "2024-11-30"),
            "get_global_news": ("2024-11-01", 7, 10),
            "get_insider_transactions": ("AAPL",)
        }
        
        for tool_name, args in news_tools.items():
            mock_yfinance = MagicMock(return_value=f"yfinance_{tool_name}_data")
            
            with patch.dict(VENDOR_METHODS[tool_name], {"yfinance": mock_yfinance}):
                set_config({"data_vendors": {"news_data": "yfinance"}})
                result = route_to_vendor(tool_name, *args)
                assert result == f"yfinance_{tool_name}_data"
                mock_yfinance.assert_called_once()
