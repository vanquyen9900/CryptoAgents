import os
import sys
import json
import sqlite3
import time
import argparse
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# Load fine-tuning env vars
FINETUNE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(FINETUNE_DIR, ".env"))

from tradingagents.agents.utils.agent_utils import build_instrument_context

DB_PATH = os.path.join(FINETUNE_DIR, "data", "db", "finetune_data.db")
JSONL_PATH = os.path.join(FINETUNE_DIR, "data", "golden_responses.jsonl")

def extract_sentiment_direction(response_text: str) -> str:
    """Attempts to extract overall sentiment direction from the response."""
    import re
    text_lower = response_text.lower()
    
    # 1. Check for explicit patterns (highest priority)
    for sentiment in ["bullish", "bearish", "neutral", "mixed"]:
        patterns = [
            rf"overall sentiment direction\s*:\s*\**{sentiment}\**",
            rf"\**overall sentiment direction\**\s*:\s*\**{sentiment}\**",
            rf"\**overall sentiment direction\**\s*–\s*\**{sentiment}\**",
            rf"sentiment direction\s*:\s*\**{sentiment}\**",
            rf"\**sentiment direction\**\s*:\s*\**{sentiment}\**",
            rf"overall sentiment\s*:\s*\**{sentiment}\**",
            rf"\**overall sentiment\**\s*:\s*\**{sentiment}\**",
        ]
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return sentiment.capitalize()
                
    # 2. Look for the sentiment word in the first few lines under the header
    lines = [line.strip().lower() for line in response_text.split("\n") if line.strip()]
    for i, line in enumerate(lines):
        if "overall sentiment direction" in line or "sentiment direction" in line or "overall sentiment" in line:
            for offset in range(1, 4):
                if i + offset < len(lines):
                    target_line = lines[i + offset]
                    for sentiment in ["bullish", "bearish", "neutral", "mixed"]:
                        if re.search(rf"\b{sentiment}\b", target_line):
                            return sentiment.capitalize()

    # 3. Check common patterns in the first 300 characters (fallback)
    snippet = text_lower[:300]
    for sentiment in ["bullish", "bearish", "neutral", "mixed"]:
        if f"**{sentiment}**" in snippet or f"*{sentiment}*" in snippet:
            return sentiment.capitalize()
            
    # Look for the first keyword that appears in the snippet
    first_idx = {}
    for sentiment in ["bullish", "bearish", "neutral", "mixed"]:
        idx = snippet.find(sentiment)
        if idx != -1:
            first_idx[sentiment] = idx
    if first_idx:
        return min(first_idx, key=first_idx.get).capitalize()
        
    # 4. Simple count check fallback
    counts = {
        "Bullish": text_lower.count("bullish"),
        "Bearish": text_lower.count("bearish"),
        "Neutral": text_lower.count("neutral"),
        "Mixed": text_lower.count("mixed")
    }
    max_sentiment = max(counts, key=counts.get)
    if counts[max_sentiment] > 0:
        return max_sentiment
        
    return "Neutral"

def evaluate_structure(response_text: str) -> tuple:
    """Checks the structural components of the generated response."""
    text_lower = response_text.lower()
    
    # 1. Source breakdown
    has_source_breakdown = any(term in text_lower for term in ["source-by-source", "breakdown", "news breakdown", "reddit breakdown", "stocktwits breakdown"])
    
    # 2. Divergence analysis
    has_divergence_analysis = any(term in text_lower for term in ["divergence", "alignment", "mismatch", "narrative"])
    
    # 3. Catalysts/risks
    has_catalysts_risks = any(term in text_lower for term in ["catalyst", "risk", "threat", "trigger"])
    
    # 4. Markdown table
    has_markdown_table = "|" in response_text and "-" in response_text
    
    # Calculate score (0.0 to 1.0)
    score_components = [has_source_breakdown, has_divergence_analysis, has_catalysts_risks, has_markdown_table]
    structure_score = sum(1.0 for c in score_components if c) / len(score_components)
    
    return has_source_breakdown, has_divergence_analysis, has_catalysts_risks, has_markdown_table, structure_score

def get_llm_client():
    fci_key = os.environ.get("FCI_API_KEY", "your-fpt-cloud-api-key-here")
    fci_url = os.environ.get("FCI_BASE_URL", "https://mkp-api.fptcloud.com/v1")
    fci_model = os.environ.get("FCI_MODEL", "gpt-oss-120b")
    
    if fci_key and fci_key != "your-fpt-cloud-api-key-here":
        print(f"Using FPT Cloud API at {fci_url} with model {fci_model}")
        return OpenAI(api_key=fci_key, base_url=fci_url), fci_model
    else:
        # Fall back to local Ollama instance
        ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        # Check if we should use qwen3:14b or qwen3:4b
        default_ollama_model = "qwen3:14b"
        print(f"FCI_API_KEY not configured. Falling back to local Ollama at {ollama_url} with model {default_ollama_model}")
        return OpenAI(api_key="ollama", base_url=ollama_url), default_ollama_model

def generate_golden_responses(limit: int = None):
    client, model_name = get_llm_client()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Find raw examples that don't have golden responses yet
    cursor.execute("""
        SELECT r.id, r.ticker, r.trade_date, r.asset_type, r.system_message 
        FROM raw_examples r
        LEFT JOIN golden_responses g ON r.id = g.raw_example_id
        WHERE g.id IS NULL
    """)
    rows = cursor.fetchall()
    
    if not rows:
        print("All raw examples already have golden responses!")
        conn.close()
        return
        
    if limit:
        rows = rows[:limit]
        print(f"Generating golden responses for {limit} examples...")
    else:
        print(f"Generating golden responses for {len(rows)} examples...")
        
    os.makedirs(os.path.dirname(JSONL_PATH), exist_ok=True)
    jsonl_file = open(JSONL_PATH, "a", encoding="utf-8")
    
    success_count = 0
    
    for row in rows:
        raw_id, ticker, trade_date, asset_type, system_message = row
        instrument_context = build_instrument_context(ticker, asset_type)
        
        # Build prompt messages
        system_content = (
            "You are a helpful AI assistant, collaborating with other assistants. "
            "If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable, "
            "prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop.\n"
            f"{system_message}\n"
            f"For your reference, the current date is {trade_date}. {instrument_context}"
        )
        
        print(f"Generating golden response for {ticker} ({trade_date})...")
        
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": "Continue"}
                ],
                temperature=0.2, # Lower temperature for stable sentiment reports
                max_tokens=1500
            )
            
            latency_ms = int((time.time() - t0) * 1000)
            golden_text = response.choices[0].message.content
            tokens_in = response.usage.prompt_tokens if response.usage else 0
            tokens_out = response.usage.completion_tokens if response.usage else 0
            
            # Analyze response
            sentiment_dir = extract_sentiment_direction(golden_text)
            has_breakdown, has_div, has_cat, has_table, struct_score = evaluate_structure(golden_text)
            
            # Save to SQLite
            cursor.execute("""
                INSERT INTO golden_responses (
                    raw_example_id, ticker, trade_date, golden_response, sentiment_direction,
                    has_source_breakdown, has_divergence_analysis, has_catalysts_risks, has_markdown_table,
                    structure_score, model_used, api_endpoint, tokens_input, tokens_output, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                raw_id, ticker, trade_date, golden_text, sentiment_dir,
                has_breakdown, has_div, has_cat, has_table, struct_score,
                model_name, client.base_url.host if hasattr(client.base_url, "host") else str(client.base_url),
                tokens_in, tokens_out, latency_ms
            ))
            conn.commit()
            
            # Get golden ID
            golden_id = cursor.lastrowid
            
            # Save to JSONL
            record = {
                "id": golden_id,
                "raw_example_id": raw_id,
                "ticker": ticker,
                "trade_date": trade_date,
                "golden_response": golden_text,
                "sentiment_direction": sentiment_dir,
                "structure_score": struct_score,
                "model_used": model_name,
                "latency_ms": latency_ms
            }
            jsonl_file.write(json.dumps(record) + "\n")
            jsonl_file.flush()
            
            success_count += 1
            print(f"Success! Sentiment: {sentiment_dir}, Structure Score: {struct_score:.2f}, Latency: {latency_ms}ms")
            
        except Exception as e:
            print(f"Error generating golden response for {ticker} ({trade_date}): {e}")
            
        # Small delay to respect rate limits if using public API
        time.sleep(1.0)
        
    jsonl_file.close()
    conn.close()
    print(f"\nGolden Response Generation Complete! Generated: {success_count} responses.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Golden Responses using FCI or local Ollama")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of responses to generate")
    args = parser.parse_args()
    
    generate_golden_responses(limit=args.limit)
