import os
import sys
import json
import sqlite3
import random
from dotenv import load_dotenv

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# Load fine-tuning env vars
FINETUNE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(FINETUNE_DIR, ".env"))

from tradingagents.agents.utils.agent_utils import build_instrument_context

DB_PATH = os.path.join(FINETUNE_DIR, "data", "db", "finetune_data.db")
DATA_OUT_DIR = os.path.join(FINETUNE_DIR, "data")

def estimate_tokens(text: str) -> int:
    """Simple word-based approximation of token count."""
    return int(len(text.split()) * 1.3)

def prepare_and_split_dataset():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Read all golden responses with their matching raw examples
    cursor.execute("""
        SELECT g.id, g.ticker, g.trade_date, g.golden_response, r.system_message, r.asset_type
        FROM golden_responses g
        JOIN raw_examples r ON g.raw_example_id = r.id
    """)
    rows = cursor.fetchall()
    
    if not rows:
        print("No golden responses found in the database. Please run 01b_generate_golden.py first!")
        conn.close()
        return
        
    print(f"Loaded {len(rows)} examples from database.")
    
    # Format and validate examples
    valid_examples = []
    for row in rows:
        golden_id, ticker, trade_date, golden_response, system_message, asset_type = row
        
        # Build exact system message that was sent to the model
        instrument_context = build_instrument_context(ticker, asset_type)
        system_content = (
            "You are a helpful AI assistant, collaborating with other assistants. "
            "If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable, "
            "prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop.\n"
            f"{system_message}\n"
            f"For your reference, the current date is {trade_date}. {instrument_context}"
        )
        
        # Validation checks
        if not golden_response.strip():
            print(f"Skipping golden_id {golden_id} due to empty golden response.")
            continue
            
        if len(system_content) < 100 or len(golden_response) < 100:
            print(f"Skipping golden_id {golden_id} due to abnormally short contents.")
            continue
            
        user_content = "Continue"
        
        approx_tokens = estimate_tokens(system_content) + estimate_tokens(golden_response)
        
        valid_examples.append({
            "golden_id": golden_id,
            "ticker": ticker,
            "trade_date": trade_date,
            "system_content": system_content,
            "user_content": user_content,
            "assistant_content": golden_response,
            "total_tokens": approx_tokens
        })
        
    print(f"Validated {len(valid_examples)}/{len(rows)} examples successfully.")
    
    # Deterministic shuffle
    random.seed(42)
    random.shuffle(valid_examples)
    
    # Split: 80% Train, 10% Val, 10% Test
    total = len(valid_examples)
    train_end = int(total * 0.8)
    val_end = train_end + int(total * 0.1)
    
    splits = {
        "train": valid_examples[:train_end],
        "val": valid_examples[train_end:val_end],
        "test": valid_examples[val_end:]
    }
    
    print(f"Splits sizes - Train: {len(splits['train'])}, Val: {len(splits['val'])}, Test: {len(splits['test'])}")
    
    # Clear existing splits in DB
    cursor.execute("DELETE FROM dataset_splits")
    conn.commit()
    
    for split_name, examples in splits.items():
        print(f"Writing {split_name} split...")
        
        # Write to JSONL
        jsonl_path = os.path.join(DATA_OUT_DIR, f"{split_name}.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for ex in examples:
                # ChatML Format for training
                chatml_format = {
                    "messages": [
                        {"role": "system", "content": ex["system_content"]},
                        {"role": "user", "content": ex["user_content"]},
                        {"role": "assistant", "content": ex["assistant_content"]}
                    ]
                }
                f.write(json.dumps(chatml_format) + "\n")
                
                # Insert into DB
                cursor.execute("""
                    INSERT INTO dataset_splits (
                        golden_id, ticker, trade_date, split, system_content, user_content, assistant_content, total_tokens
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ex["golden_id"], ex["ticker"], ex["trade_date"], split_name,
                    ex["system_content"], ex["user_content"], ex["assistant_content"], ex["total_tokens"]
                ))
        conn.commit()
        print(f"Saved {split_name} split to {jsonl_path} and SQLite.")
        
    conn.close()
    print("\nDataset preparation and splitting complete!")

if __name__ == "__main__":
    prepare_and_split_dataset()
