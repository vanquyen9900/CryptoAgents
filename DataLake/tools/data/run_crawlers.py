import subprocess
import sys
import os
from pathlib import Path

def run():
    print("Starting DataLake Crawlers & Builders...")
    datalake_dir = Path(__file__).resolve().parents[2]
    crawlers_dir = datalake_dir / "crawlers"
    builders_dir = datalake_dir / "builders"

    # 1. Calendar
    print("\n--- Running Calendar Crawler (Phase 1/A) ---")
    res = subprocess.run([sys.executable, str(crawlers_dir / "calendar_crawler.py")])
    if res.returncode != 0: raise SystemExit("Calendar Crawler failed.")

    # 2. Instrument Master
    print("\n--- Running Instrument Master Crawler (Phase B) ---")
    res = subprocess.run([sys.executable, str(crawlers_dir / "instrument_master_crawler.py")])
    if res.returncode != 0: raise SystemExit("Instrument Master Crawler failed.")

    # 3. OHLCV
    print("\n--- Running OHLCV Crawler (Phase 2/A) ---")
    res = subprocess.run([sys.executable, str(crawlers_dir / "ohlcv_crawler.py")])
    if res.returncode != 0: raise SystemExit("OHLCV Crawler failed.")

    # 4. Technical Indicators
    print("\n--- Running Technical Indicators Crawler (Phase C) ---")
    res = subprocess.run([sys.executable, str(crawlers_dir / "technical_indicators.py")])
    if res.returncode != 0: raise SystemExit("Technical Indicators Crawler failed.")

    # 5. Fundamentals
    print("\n--- Running Fundamentals Crawler (Phase D) ---")
    subprocess.run([sys.executable, str(crawlers_dir / "fundamentals_crawler.py")])

    # 6. News
    print("\n--- Running News Crawler (Phase E) ---")
    subprocess.run([sys.executable, str(crawlers_dir / "news_crawler.py")])

    # 7. Social
    print("\n--- Running Social Crawler (Phase F) ---")
    subprocess.run([sys.executable, str(crawlers_dir / "social_crawler.py")])

    # 8. Macro
    print("\n--- Running Macro Crawler (Phase G) ---")
    subprocess.run([sys.executable, str(crawlers_dir / "macro_crawler.py")])

    # 9. Labels
    print("\n--- Running Labels Builder (Phase H) ---")
    res = subprocess.run([sys.executable, str(builders_dir / "labels_builder.py")])
    if res.returncode != 0: raise SystemExit("Labels Builder failed.")

    # 10. Snapshots
    print("\n--- Running Snapshots Builder (Phase I) ---")
    res = subprocess.run([sys.executable, str(builders_dir / "snapshot_builder.py")])
    if res.returncode != 0: raise SystemExit("Snapshots Builder failed.")

    print("\nAll crawlers and builders finished.")

if __name__ == "__main__":
    run()
