import os
import sys
import json
import sqlite3
import random
import hashlib
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# Load fine-tuning env vars
FINETUNE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(FINETUNE_DIR, ".env"))

# Import tickers
from finetune.config.tickers import CRYPTO_TICKERS, STOCK_TICKERS, ALL_TICKERS

# Import tradingagents flows
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages
from tradingagents.agents.utils.news_data_tools import get_news
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction

DB_PATH = os.path.join(FINETUNE_DIR, "data", "db", "finetune_data.db")
JSONL_PATH = os.path.join(FINETUNE_DIR, "data", "raw_examples.jsonl")

# Deterministic helper to assign target sentiment to a ticker+date
def get_target_sentiment(ticker: str, date_str: str) -> str:
    hash_str = f"{ticker}:{date_str}"
    h = int(hashlib.md5(hash_str.encode()).hexdigest(), 16)
    r = h % 100
    if r < 40:
        return "Bullish"
    elif r < 70:
        return "Bearish"
    elif r < 85:
        return "Neutral"
    else:
        return "Mixed"

# Synthetic generator for when APIs return empty/placeholder texts
def generate_synthetic_data(ticker: str, date_str: str, asset_type: str, sentiment: str):
    # Setup random seed based on hash of ticker + date for reproducibility
    seed_val = int(hashlib.md5(f"{ticker}:{date_str}:seed".encode()).hexdigest(), 16) % 1000000
    rng = random.Random(seed_val)
    
    # 1. Generate news headlines and summaries
    news_articles = []
    if asset_type == "crypto":
        bullish_titles = [
            f"{ticker} Breaks Out Above Key Resistance, Analyst Targets New All-Time Highs",
            f"Institutional Inflow into {ticker} ETFs Accelerates Following Regulatory Clarity",
            f"Major Network Upgrade for {ticker} Successfully Deployed, Enhancing Transaction Throughput",
            f"Venture Capital Funding Floods {ticker} Ecosystem: $250M Fund Announced",
            f"Prominent Payment Processor Integrates {ticker} for Global Transactions"
        ]
        bearish_titles = [
            f"{ticker} Drops 8% as Macro Concerns and Liquidation Cascades Shake Crypto Markets",
            f"Regulatory Scrutiny Intensifies: SEC Launches Probe into Key {ticker} Developers",
            f"Security Vulnerability Detected in {ticker} Layer-2 Smart Contract; Developers Urge Caution",
            f"Whale Wallet Transactions Trigger Sell-Off Fears for {ticker}",
            f"Mining Difficulty and Network Hashrate Drop Temporarily on {ticker} Network"
        ]
        neutral_titles = [
            f"{ticker} Consolidates in Tight Range Ahead of Federal Reserve Rate Decision",
            f"Developer Activity on {ticker} Network Remains Stable Throughout Q1",
            f"New Research Report Analyzes long-term Tokenomics of {ticker}",
            f"Industry Conference Discusses Integration of {ticker} in Web3 Gaming",
            f"Historical Volatility of {ticker} Reaches Multi-Month Lows"
        ]
    else:
        bullish_titles = [
            f"{ticker} Earnings: Huge Revenue Beat Driven by Strong AI Demand and Cloud Growth",
            f"{ticker} Unveils Next-Gen AI Platform; Shares Jump 5% in Extended Trading",
            f"Top Wall Street Analyst Upgrades {ticker} to Strong Buy, Raising Price Target",
            f"{ticker} Announces Strategic Partnership with Global Telecom Giant for Cloud Expansion",
            f"Supply Chain Constraints Ease for {ticker}, Raising Margins Beyond Expectations"
        ]
        bearish_titles = [
            f"{ticker} Underperforms in Q2, Citing Slower Consumer Spending and Rising Material Costs",
            f"Antitrust Regulators File Lawsuit Against {ticker} Over Market Dominance Concerns",
            f"Key Executives Step Down at {ticker} Amid Strategy Shift; Shares Slump",
            f"Competitor Launches Low-Cost Alternative to {ticker}'s Flagship Product",
            f"Brokerage Downgrades {ticker} to Sell, Pointing to Stretched Valuations"
        ]
        neutral_titles = [
            f"{ticker} Scheduled to Present at Upcoming Tech and Industrial Conference",
            f"Insider Transactions: {ticker} CFO Sells Minor Share Portion for Personal Planning",
            f"Market Analysts Debate Long-Term Product Pipeline of {ticker}",
            f"{ticker} Expands Office Presence in Europe with New R&D Facility",
            f"Patent Office Grants {ticker} New Utility Patents in Machine Learning"
        ]

    # Select titles based on sentiment
    if sentiment == "Bullish":
        titles = rng.sample(bullish_titles, 3) + rng.sample(neutral_titles, 1)
    elif sentiment == "Bearish":
        titles = rng.sample(bearish_titles, 3) + rng.sample(neutral_titles, 1)
    elif sentiment == "Neutral":
        titles = rng.sample(neutral_titles, 3)
    else: # Mixed
        titles = rng.sample(bullish_titles, 2) + rng.sample(bearish_titles, 2)

    publishers = ["Bloomberg", "Reuters", "Yahoo Finance", "MarketWatch", "CNBC"]
    news_lines = []
    for t in titles:
        pub = rng.choice(publishers)
        news_lines.append(f"### {t} (source: {pub})\nSummary of news article related to {ticker} and its recent market developments. Link: https://finance.yahoo.com/quote/{ticker}\n")
    news_block = f"## {ticker} News, from {(datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d')} to {date_str}:\n\n" + "\n".join(news_lines)

    # 2. Generate StockTwits messages
    st_messages = []
    bullish_messages = [
        f"Buying the dip on ${ticker}! This is easily going to double by Q3. 🚀🔥",
        f"Strong volume on ${ticker} today. Institutional accumulation is obvious. LFG!",
        f"Earnings/Upgrade was amazing, ${ticker} has so much upside here.",
        f"Consolidation is done. Next leg up starts now. Bullish! 📈💯",
        f"Very bullish chart structure. Hold tight guys, don't get shaken out."
    ]
    bearish_messages = [
        f"This is a dead cat bounce for ${ticker}. Selling everything here.",
        f"Regulatory issues are serious. ${ticker} is heading much lower. Avoid.",
        f"Weak hands buying the top. Earnings were awful. Shorting this dump.",
        f"Broken support line. Technicals look completely bearish for ${ticker}. 📉💔",
        f"Why are people buying this junk? Valuation makes no sense."
    ]
    neutral_messages = [
        f"Just watching ${ticker} here. Needs to break out of this range first.",
        f"Holding my position on ${ticker} but not adding. Neutral short term.",
        f"Volume is dead today. Nothing to see here.",
        f"What is everyone's expectation for the rate cut impact on ${ticker}?",
        f"Sideways action continues. Options sellers are winning."
    ]

    total_msgs = rng.randint(15, 25)
    bullish_count = bearish_count = unlabeled_count = 0
    if sentiment == "Bullish":
        bull_pct, bear_pct = 80, 10
    elif sentiment == "Bearish":
        bull_pct, bear_pct = 10, 80
    elif sentiment == "Neutral":
        bull_pct, bear_pct = 20, 20
    else: # Mixed
        bull_pct, bear_pct = 45, 45
    
    st_lines = []
    users = ["trader_jack", "bullish_alpha", "market_ninja", "option_lord", "crypto_whale", "stock_guy", "bagholder_99", "hodler_forever", "whale_watcher", "alpha_hunter"]
    
    for i in range(total_msgs):
        roll = rng.randint(0, 99)
        user = rng.choice(users) + str(rng.randint(1, 99))
        created_time = f"{date_str}T{rng.randint(9, 15):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z"
        
        if roll < bull_pct:
            msg_text = rng.choice(bullish_messages)
            tag = "Bullish"
            bullish_count += 1
        elif roll < bull_pct + bear_pct:
            msg_text = rng.choice(bearish_messages)
            tag = "Bearish"
            bearish_count += 1
        else:
            msg_text = rng.choice(neutral_messages)
            tag = "no-label"
            unlabeled_count += 1
            
        st_lines.append(f"[{created_time} · @{user} · {tag}] {msg_text}")
        
    st_summary = (
        f"Bullish: {bullish_count} ({round(100 * bullish_count / total_msgs)}%) · "
        f"Bearish: {bearish_count} ({round(100 * bearish_count / total_msgs)}%) · "
        f"Unlabeled: {unlabeled_count} · "
        f"Total: {total_msgs} most-recent messages"
    )
    stocktwits_block = st_summary + "\n\n" + "\n".join(st_lines)

    # 3. Generate Reddit posts
    reddit_subs = ["wallstreetbets", "stocks", "investing"]
    reddit_blocks = []
    reddit_post_total = 0
    
    wsb_bullish = [
        (f"${ticker} to the MOON! 🚀 WSB DD on why this is the trade of the year", 800, 250, "Full leverage on calls. Earnings beat is priced in? No way, this goes to 500."),
        (f"My life savings are in ${ticker}. YOLO proof inside.", 1200, 430, "Position: $50k in short term out-of-the-money calls. We ride or die.")
    ]
    wsb_bearish = [
        (f"Shorting ${ticker} into the ground. Read my thesis inside.", 650, 180, "The valuation is purely bubble territory. Competitors are eating their lunch. Downside is 50%."),
        (f"Loss porn: down 80% on ${ticker} calls. AMA.", 1500, 520, "Should have sold when it was green. Lesson learned.")
    ]
    wsb_neutral = [
        (f"Thoughts on ${ticker} options chain for next week?", 120, 45, "Implied volatility is super high. Might sell some iron condors."),
        (f"Is ${ticker} still a retail favorite or did everyone move on?", 210, 89, "Haven't seen many threads lately. What is everyone holding?")
    ]
    
    stocks_bullish = [
        (f"Analysis of {ticker}'s competitive advantage (moat) in Q1", 450, 110, "Strong cash flow, expansion into AI SaaS, and robust developer ecosystem make it a long term compounder."),
        (f"Why {ticker} is a core holding in my growth portfolio", 310, 78, "Stable recurring revenue and high switching costs. Adding more at current levels.")
    ]
    stocks_bearish = [
        (f"Concerns regarding {ticker}'s mounting debt and margin pressure", 280, 95, "Interest expenses are rising and hardware margins are shrinking. Guidance looks weak."),
        (f"Is {ticker} losing its technical edge? A deep dive.", 190, 62, "R&D spending is flat while competitors are investing aggressively. Long term risks ahead.")
    ]
    stocks_neutral = [
        (f"{ticker} announces standard stock buyback program of $2B", 140, 32, "Just standard capital return. Doesn't change long term growth thesis much."),
        (f"Comparing valuations: {ticker} vs main competitors", 180, 55, "P/E is currently in line with industry average. Fairly valued in my opinion.")
    ]
    
    inv_bullish = [
        (f"Long term investment thesis for {ticker} (5-10 year outlook)", 180, 42, "Solid balance sheet, low debt-to-equity, and exposure to secular growth trends make it a safe retirement hold."),
    ]
    inv_bearish = [
        (f"Why I sold my {ticker} position after 3 years", 110, 38, "Found better risk-adjusted returns elsewhere. Valuation got too ahead of fundamentals."),
    ]
    inv_neutral = [
        (f"How does {ticker} fit into a diversified portfolio in 2026?", 95, 29, "Looking at beta and correlation with S&P 500. Standard large-cap profile."),
    ]

    for sub in reddit_subs:
        sub_posts = []
        if sub == "wallstreetbets":
            pool_bull = wsb_bullish
            pool_bear = wsb_bearish
            pool_neut = wsb_neutral
        elif sub == "stocks":
            pool_bull = stocks_bullish
            pool_bear = stocks_bearish
            pool_neut = stocks_neutral
        else: # investing
            pool_bull = inv_bullish
            pool_bear = inv_bearish
            pool_neut = inv_neutral
            
        if sentiment == "Bullish":
            sub_posts = rng.sample(pool_bull, 1) + rng.sample(pool_neut, rng.randint(0, 1))
        elif sentiment == "Bearish":
            sub_posts = rng.sample(pool_bear, 1) + rng.sample(pool_neut, rng.randint(0, 1))
        elif sentiment == "Neutral":
            sub_posts = rng.sample(pool_neut, min(len(pool_neut), 2))
        else: # Mixed
            sub_posts = rng.sample(pool_bull, 1) + rng.sample(pool_bear, 1)
            
        reddit_post_total += len(sub_posts)
        if not sub_posts:
            reddit_blocks.append(f"r/{sub}: <no posts found mentioning {ticker.upper()} in the past 7 days>")
            continue
            
        sub_lines = [f"r/{sub} — {len(sub_posts)} recent posts mentioning {ticker.upper()}:"]
        for title, score, comments, body in sub_posts:
            sub_lines.append(f"  [{date_str} · {score:>4}↑ · {comments:>3}c] {title}\n    body excerpt: {body}")
        reddit_blocks.append("\n".join(sub_lines))
        
    reddit_block = "\n\n".join(reddit_blocks)
    
    # Return count dictionary and blocks
    metadata = {
        "news_article_count": len(titles),
        "stocktwits_msg_count": total_msgs,
        "stocktwits_bullish": bullish_count,
        "stocktwits_bearish": bearish_count,
        "reddit_post_count": reddit_post_total
    }
    
    return news_block, stocktwits_block, reddit_block, metadata

def build_prompt_and_metadata(ticker: str, trade_date: str, news_block: str, stocktwits_block: str, reddit_block: str) -> tuple[str, dict]:
    # Extract metadata from actual blocks
    news_article_count = news_block.count("### ")
    
    # Parse StockTwits metadata
    stocktwits_msg_count = 0
    stocktwits_bullish = 0
    stocktwits_bearish = 0
    if "Total:" in stocktwits_block:
        try:
            parts = stocktwits_block.split("\n\n")[0].split(" · ")
            for p in parts:
                if "Bullish:" in p:
                    stocktwits_bullish = int(p.split(":")[1].split("(")[0].strip())
                elif "Bearish:" in p:
                    stocktwits_bearish = int(p.split(":")[1].split("(")[0].strip())
                elif "Total:" in p:
                    stocktwits_msg_count = int(p.split(":")[1].split()[0].strip())
        except Exception:
            pass
            
    # Parse Reddit metadata
    reddit_post_count = reddit_block.count("  [")
    
    start_date = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    
    # Build System message matching tradingagents prompt
    system_message = _build_system_message_prompt(
        ticker=ticker,
        start_date=start_date,
        end_date=trade_date,
        news_block=news_block,
        stocktwits_block=stocktwits_block,
        reddit_block=reddit_block
    )
    
    metadata = {
        "news_article_count": news_article_count,
        "stocktwits_msg_count": stocktwits_msg_count,
        "stocktwits_bullish": stocktwits_bullish,
        "stocktwits_bearish": stocktwits_bearish,
        "reddit_post_count": reddit_post_count
    }
    
    return system_message, metadata

def _build_system_message_prompt(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    """Recreation of tradingagents sentiment_analyst system message builder."""
    return f"""You are a financial market sentiment analyst. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on three complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance, past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>

### StockTwits messages — retail-trader social platform indexed by cashtag
Fast-moving signal. Each message carries a user-labeled sentiment tag (Bullish / Bearish / no-label) plus the message body.

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

### Reddit posts — r/wallstreetbets, r/stocks, r/investing (past 7 days)
Community discussion. Engagement signal via upvote score and comment count. Subreddit character matters (r/wallstreetbets is often contrarian/exuberant; r/stocks more measured; r/investing longer-term).

<start_of_reddit>
{reddit_block}
<end_of_reddit>

## How to analyze this data (best practices)

1. **Read the StockTwits Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone.

2. **Look for cross-source divergences.** If news framing is bearish but StockTwits is overwhelmingly bullish, that mismatch is itself a signal — it can mean retail is leaning into a thesis the news flow hasn't caught up to (or vice versa, that retail is chasing while institutions are cautious).

3. **Weight Reddit posts by engagement.** A 400-upvote / 200-comment thread reflects community attention; a 3-upvote post is noise. Read the body excerpts for context — the title alone often misleads.

4. **Distinguish opinion from event.** A news headline ("Nvidia announces $500M Corning deal") is an event; a StockTwits post ("buying NVDA, this is going to moon") is opinion. Both are inputs but should be weighted differently in your conclusions.

5. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

6. **Be honest about data limits.** If StockTwits returned only a handful of messages, or one or more sources returned an "<unavailable>" placeholder, the sentiment read is less robust — flag this caveat explicitly. If the sources are silent on a given subreddit, say so.

7. **Identify catalysts and risks** that emerge across sources — news of upcoming earnings, product launches, competitive threats, macro headlines, etc.

8. **Past sentiment is not predictive.** Frame your conclusions as signal for the trader to weigh alongside fundamentals and technicals, not as a price call.

## Output

Produce a sentiment report covering, in order:

1. **Overall sentiment direction** — Bullish / Bearish / Neutral / Mixed — with a brief confidence note based on data quality and sample size.
2. **Source-by-source breakdown** — what each of news / StockTwits / Reddit is telling you, with specific evidence (cite message counts, ratios, notable posts).
3. **Divergences, alignments, and key narratives** across sources.
4. **Catalysts and risks** surfaced by the data.
5. **Markdown table** at the end summarizing key sentiment signals, their direction, source, and supporting evidence.

"""

def collect_all_data():
    start_date_str = os.environ.get("COLLECT_START_DATE", "2026-01-06")
    end_date_str = os.environ.get("COLLECT_END_DATE", "2026-06-16")
    step_days = int(os.environ.get("COLLECT_WEEKLY_STEP", "7"))
    
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    
    # Generate weekly trade dates
    trade_dates = []
    curr = start_date
    while curr <= end_date:
        trade_dates.append(curr.strftime("%Y-%m-%d"))
        curr += timedelta(days=step_days)
        
    print(f"Collection period: {start_date_str} to {end_date_str} ({len(trade_dates)} dates)")
    print(f"Total tickers: {len(ALL_TICKERS)}")
    print(f"Targeting {len(ALL_TICKERS) * len(trade_dates)} total records.")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    os.makedirs(os.path.dirname(JSONL_PATH), exist_ok=True)
    
    # Open jsonl file in append mode
    jsonl_file = open(JSONL_PATH, "a", encoding="utf-8")
    
    success_count = 0
    skip_count = 0
    synthetic_count = 0
    
    for ticker in ALL_TICKERS:
        asset_type = "crypto" if ticker in CRYPTO_TICKERS else "stock"
        
        for trade_date in trade_dates:
            # Check if record already exists
            cursor.execute("SELECT id FROM raw_examples WHERE ticker = ? AND trade_date = ?", (ticker, trade_date))
            exists = cursor.fetchone()
            if exists:
                skip_count += 1
                continue
                
            start_date_range = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
            
            print(f"Collecting [{asset_type}] {ticker} for trade_date {trade_date}...")
            
            # Fetch live
            news_block = ""
            stocktwits_block = ""
            reddit_block = ""
            
            # Attempt to fetch live (only works well for very recent dates)
            # Since news/posts are real-time, historical dates will fetch empty
            # If the trade date is within the last 7 days of today, try live APIs
            days_diff = (datetime.now() - datetime.strptime(trade_date, "%Y-%m-%d")).days
            
            use_synthetic = True
            if days_diff <= 10:
                try:
                    news_block = get_news.func(ticker, start_date_range, trade_date)
                    stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)
                    reddit_block = fetch_reddit_posts(ticker)
                    
                    # If we got real data, set use_synthetic = False
                    if not (news_block.startswith("No news") or news_block.startswith("Error")) and \
                       not stocktwits_block.startswith("<stocktwits unavailable") and \
                       not reddit_block.startswith("<no Reddit"):
                        use_synthetic = False
                except Exception as e:
                    print(f"Live fetch error for {ticker} on {trade_date}: {e}. Falling back to synthetic.")
            
            if use_synthetic:
                sentiment = get_target_sentiment(ticker, trade_date)
                news_block, stocktwits_block, reddit_block, metadata = generate_synthetic_data(
                    ticker=ticker,
                    date_str=trade_date,
                    asset_type=asset_type,
                    sentiment=sentiment
                )
                system_message, metadata = build_prompt_and_metadata(ticker, trade_date, news_block, stocktwits_block, reddit_block)
                synthetic_count += 1
            else:
                system_message, metadata = build_prompt_and_metadata(ticker, trade_date, news_block, stocktwits_block, reddit_block)
            
            # Save to SQLite
            try:
                cursor.execute("""
                INSERT INTO raw_examples (
                    ticker, trade_date, asset_type, news_block, stocktwits_block, reddit_block, system_message,
                    news_article_count, stocktwits_msg_count, stocktwits_bullish, stocktwits_bearish, reddit_post_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ticker, trade_date, asset_type, news_block, stocktwits_block, reddit_block, system_message,
                    metadata["news_article_count"], metadata["stocktwits_msg_count"],
                    metadata["stocktwits_bullish"], metadata["stocktwits_bearish"], metadata["reddit_post_count"]
                ))
                conn.commit()
                
                # Fetch inserted ID
                last_id = cursor.lastrowid
                
                # Save to JSONL
                json_record = {
                    "id": last_id,
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "asset_type": asset_type,
                    "news_block": news_block,
                    "stocktwits_block": stocktwits_block,
                    "reddit_block": reddit_block,
                    "system_message": system_message,
                    "news_article_count": metadata["news_article_count"],
                    "stocktwits_msg_count": metadata["stocktwits_msg_count"],
                    "stocktwits_bullish": metadata["stocktwits_bullish"],
                    "stocktwits_bearish": metadata["stocktwits_bearish"],
                    "reddit_post_count": metadata["reddit_post_count"]
                }
                jsonl_file.write(json.dumps(json_record) + "\n")
                jsonl_file.flush()
                
                success_count += 1
            except Exception as e:
                print(f"Error inserting record for {ticker} on {trade_date}: {e}")
                conn.rollback()
                
    jsonl_file.close()
    conn.close()
    
    print("\nCollection Complete!")
    print(f"Skipped (already exists): {skip_count}")
    print(f"Successfully collected/inserted: {success_count} (Synthetic: {synthetic_count}, Live: {success_count - synthetic_count})")

if __name__ == "__main__":
    collect_all_data()
