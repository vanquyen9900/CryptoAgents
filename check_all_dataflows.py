import sys
import time
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG

# Ensure we use yfinance for testing as it doesn't require API keys
config = DEFAULT_CONFIG.copy()
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
    "quantitative_analysis": "yfinance",
}
set_config(config)

def run_test(test_name, func, *args, **kwargs):
    print(f"\n==================================================")
    print(f" TESTING: {test_name}")
    print(f"==================================================")
    start = time.time()
    try:
        res = func(*args, **kwargs)
        elapsed = time.time() - start
        print(f" Status: SUCCESS (Took {elapsed:.2f}s)")
        print(f" Result type: {type(res)}")
        # Print a preview of the result
        res_str = str(res)
        preview_len = min(400, len(res_str))
        print(f" Preview (first {preview_len} chars):\n{res_str[:preview_len]}")
        if len(res_str) > preview_len:
            print("... [TRUNCATED] ...")
        return True
    except Exception as e:
        elapsed = time.time() - start
        print(f" Status: FAILED (Took {elapsed:.2f}s)")
        print(f" Error: {e}")
        return False

def main():
    print("Starting Comprehensive Dataflow Check for CryptoAgents...")
    print("Using Yahoo Finance (yfinance) as the data provider.")
    
    results = {}
    
    # 1. Test Stock OHLCV Data
    results["Stock OHLCV (AAPL)"] = run_test(
        "Stock OHLCV Data (AAPL)",
        route_to_vendor, "get_stock_data", "AAPL", "2024-11-01", "2024-11-10"
    )
    
    # 2. Test Crypto OHLCV Data
    results["Crypto OHLCV (BTC-USD)"] = run_test(
        "Crypto OHLCV Data (BTC-USD)",
        route_to_vendor, "get_stock_data", "BTC-USD", "2026-01-01", "2026-01-10"
    )
    
    # 3. Test Technical Indicators
    results["Technical Indicators (AAPL macd)"] = run_test(
        "Technical Indicators (AAPL - macd)",
        route_to_vendor, "get_indicators", "AAPL", "macd", "2024-11-01", 10
    )
    
    # 4. Test Stock Fundamentals
    results["Stock Fundamentals (AAPL)"] = run_test(
        "Stock Fundamentals (AAPL)",
        route_to_vendor, "get_fundamentals", "AAPL"
    )
    
    # 5. Test Crypto Fundamentals Bypassing (should return a standard "not applicable" message)
    results["Crypto Fundamentals Bypass (BTC-USD)"] = run_test(
        "Crypto Fundamentals Bypass (BTC-USD)",
        route_to_vendor, "get_fundamentals", "BTC-USD"
    )
    
    # 6. Test Balance Sheet
    results["Balance Sheet (AAPL)"] = run_test(
        "Balance Sheet (AAPL)",
        route_to_vendor, "get_balance_sheet", "AAPL"
    )
    
    # 7. Test Stock News
    results["Stock News (AAPL)"] = run_test(
        "Stock News (AAPL)",
        route_to_vendor, "get_news", "AAPL", "2024-11-01", "2024-11-05"
    )
    
    # 8. Test Global Macro News
    results["Global News"] = run_test(
        "Global News",
        route_to_vendor, "get_global_news", "2024-11-01", 3, 5
    )
    
    # 9. Test Insider Transactions
    results["Insider Transactions (AAPL)"] = run_test(
        "Insider Transactions (AAPL)",
        route_to_vendor, "get_insider_transactions", "AAPL"
    )
    
    # 10. Test TensorFlow Anomaly Detection (calls local model train/inference)
    results["Quantitative Anomaly Detection"] = run_test(
        "TensorFlow Anomaly Detection (BTC-USD)",
        route_to_vendor, "get_anomaly_signals", "BTC-USD", "2026-01-30", 15
    )
    
    # 11. Test TensorFlow Trend Prediction (calls local model train/inference)
    results["Quantitative Trend Prediction"] = run_test(
        "TensorFlow Trend Prediction (BTC-USD)",
        route_to_vendor, "get_trend_predictions", "BTC-USD", "2026-01-30", 15
    )
    
    print("\n==================================================")
    print(" SUMMARY OF DATAFLOW CHECKS")
    print("==================================================")
    all_passed = True
    for name, success in results.items():
        status = "PASSED" if success else "FAILED"
        print(f" - {name:40}: {status}")
        if not success:
            all_passed = False
            
    if all_passed:
        print("\nAll dataflows are clear! You are ready to run the project.")
    else:
        print("\nSome dataflows failed. Please check the logs above.")

if __name__ == "__main__":
    main()
