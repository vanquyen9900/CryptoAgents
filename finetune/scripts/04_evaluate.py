import os
import sys
import json
import sqlite3
import time
import random
import argparse
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from rouge_score import rouge_scorer
from tabulate import tabulate

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# Load fine-tuning env vars
FINETUNE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(FINETUNE_DIR, ".env"))

import importlib
generate_golden = importlib.import_module("finetune.scripts.01b_generate_golden")
extract_sentiment_direction = generate_golden.extract_sentiment_direction
evaluate_structure = generate_golden.evaluate_structure

DB_PATH = os.path.join(FINETUNE_DIR, "data", "db", "finetune_data.db")
EVAL_OUT_DIR = os.path.join(FINETUNE_DIR, "eval_results")

# Go/No-Go Thresholds
GO_NO_GO_LIMITS = {
    "structure_score": 0.80,
    "rouge1_f": 0.35,
    "accuracy": 0.70,
    "judge_avg": 3.0
}

def get_judge_client():
    fci_key = os.environ.get("FCI_API_KEY", "your-fpt-cloud-api-key-here")
    fci_url = os.environ.get("FCI_BASE_URL", "https://mkp-api.fptcloud.com/v1")
    fci_model = os.environ.get("FCI_MODEL", "gpt-oss-120b")
    
    if fci_key and fci_key != "your-fpt-cloud-api-key-here":
        return OpenAI(api_key=fci_key, base_url=fci_url), fci_model
    else:
        ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return OpenAI(api_key="ollama", base_url=ollama_url), "qwen3:14b"

def run_gpt_judge(client, judge_model, system_prompt, user_prompt, reference, response):
    """Run GPT-as-Judge on a response compared to the golden reference."""
    judge_system = """You are an expert financial analysis quality judge. Evaluate the student LLM's sentiment report against the Teacher's Golden Reference.
Provide scores on a scale of 1.0 to 5.0 (1 = completely incorrect/absent, 5 = perfect alignment with Golden Reference) for each of the following 5 dimensions.

Return your evaluation EXACTLY in the following JSON format:
{
  "accuracy": 4.5,
  "evidence": 4.0,
  "structure": 5.0,
  "actionability": 3.5,
  "nuance": 4.0,
  "justification": "Detailed explanation of your scores..."
}

Dimensions:
1. accuracy: Is the predicted sentiment correct and are details factual relative to the reference?
2. evidence: Does the response cite specific message counts, percentages, and events as the reference does?
3. structure: Does it follow the correct 5 sections (Sentiment direction, breakdown, divergence, catalysts/risks, markdown table)?
4. actionability: Is it written as a signal for trading, not a definitive price forecast?
5. nuance: Does it capture the market subtleties, conflicts, and gaps in data mentioned in the reference?
"""

    judge_user = f"""[System Prompt under test]:
{system_prompt}

[User Prompt]:
{user_prompt}

[Golden Reference Response]:
{reference}

[Student Response under test]:
{response}
"""

    try:
        completion = client.chat.completions.create(
            model=judge_model,
            messages=[
                {"role": "system", "content": judge_system},
                {"role": "user", "content": judge_user}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        scores = json.loads(completion.choices[0].message.content)
        
        # Calculate average
        avg = sum(scores[k] for k in ["accuracy", "evidence", "structure", "actionability", "nuance"]) / 5.0
        scores["average"] = avg
        return scores
    except Exception as e:
        print(f"Error running GPT-as-Judge: {e}")
        return None

def evaluate_model(model_name: str, limit: int = None):
    print(f"\nEvaluating model: {model_name}")
    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_client = OpenAI(api_key="ollama", base_url=ollama_url)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Read test split
    cursor.execute("""
        SELECT id, ticker, trade_date, system_content, user_content, assistant_content 
        FROM dataset_splits 
        WHERE split = 'test'
    """)
    test_rows = cursor.fetchall()
    
    if not test_rows:
        print("No test split found in dataset_splits table. Run 02_prepare_dataset.py first.")
        conn.close()
        return
        
    if limit:
        test_rows = test_rows[:limit]
        
    print(f"Found {len(test_rows)} test examples.")
    
    # Setup output directory
    os.makedirs(EVAL_OUT_DIR, exist_ok=True)
    jsonl_out_path = os.path.join(EVAL_OUT_DIR, f"{model_name.replace(':', '_')}_eval_results.jsonl")
    jsonl_file = open(jsonl_out_path, "w", encoding="utf-8")
    
    # Setup Rouge Scorer
    scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
    
    # Select sample indices for GPT-as-Judge (e.g. 20 samples)
    judge_limit = int(os.environ.get("EVAL_JUDGE_SAMPLES", "20"))
    random.seed(42) # Fixed seed to evaluate same samples across models
    judge_indices = set(random.sample(range(len(test_rows)), min(judge_limit, len(test_rows))))
    
    judge_client, judge_model = get_judge_client()
    
    # Clear previous evaluation results for this model in SQLite
    cursor.execute("DELETE FROM eval_results WHERE model_name = ?", (model_name,))
    conn.commit()
    
    evaluated_count = 0
    total_latency_ms = 0
    
    for idx, row in enumerate(test_rows):
        split_id, ticker, trade_date, system_content, user_content, assistant_content = row
        
        print(f"[{idx+1}/{len(test_rows)}] Running inference for {ticker} ({trade_date})...")
        
        t0 = time.time()
        try:
            # Query Ollama
            response = ollama_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.2,
                max_tokens=1500
            )
            
            latency_ms = int((time.time() - t0) * 1000)
            total_latency_ms += latency_ms
            model_response = response.choices[0].message.content
            
            # Compute structure score
            has_breakdown, has_div, has_cat, has_table, struct_score = evaluate_structure(model_response)
            
            # Compute ROUGE
            scores = scorer.score(assistant_content, model_response)
            r1_f = scores['rouge1'].fmeasure
            r2_f = scores['rouge2'].fmeasure
            rl_f = scores['rougeL'].fmeasure
            
            # Sentiment Accuracy
            pred_sentiment = extract_sentiment_direction(model_response)
            ref_sentiment = extract_sentiment_direction(assistant_content)
            sentiment_match = 1 if pred_sentiment == ref_sentiment else 0
            
            # GPT-as-Judge
            judge_scores = None
            if idx in judge_indices:
                print(f"Running GPT-as-Judge for index {idx}...")
                judge_scores = run_gpt_judge(
                    judge_client, judge_model, system_content, user_content, assistant_content, model_response
                )
            
            # Save to SQLite
            cursor.execute("""
                INSERT INTO eval_results (
                    model_name, test_example_id, ticker, trade_date, model_response,
                    structure_score, rouge1_f, rouge2_f, rougeL_f,
                    sentiment_direction_pred, sentiment_direction_ref, sentiment_match,
                    judge_accuracy, judge_evidence, judge_structure, judge_actionability, judge_nuance, judge_average
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                model_name, split_id, ticker, trade_date, model_response,
                struct_score, r1_f, r2_f, rl_f,
                pred_sentiment, ref_sentiment, sentiment_match,
                judge_scores["accuracy"] if judge_scores else None,
                judge_scores["evidence"] if judge_scores else None,
                judge_scores["structure"] if judge_scores else None,
                judge_scores["actionability"] if judge_scores else None,
                judge_scores["nuance"] if judge_scores else None,
                judge_scores["average"] if judge_scores else None
            ))
            conn.commit()
            
            # Save to JSONL
            record = {
                "model_name": model_name,
                "test_example_id": split_id,
                "ticker": ticker,
                "trade_date": trade_date,
                "latency_ms": latency_ms,
                "structure_score": struct_score,
                "rouge1_f": r1_f,
                "sentiment_match": sentiment_match,
                "judge_scores": judge_scores
            }
            jsonl_file.write(json.dumps(record) + "\n")
            jsonl_file.flush()
            
            evaluated_count += 1
            print(f"Done! ROUGE-1: {r1_f:.3f}, Struct Score: {struct_score:.2f}, Match: {sentiment_match == 1}")
            
        except Exception as e:
            print(f"Failed to evaluate {ticker} on {trade_date}: {e}")
            
    jsonl_file.close()
    conn.close()
    
    avg_lat = total_latency_ms / evaluated_count if evaluated_count else 0
    print(f"\nEvaluation of {model_name} completed! Evaluated {evaluated_count} examples. Avg Latency: {avg_lat:.1f}ms")

def compare_models():
    print("\n=======================================================")
    print("COMPARING EVALUATION RESULTS (Baseline vs Fine-tuned)")
    print("=======================================================\n")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT model_name,
               COUNT(*) as total_samples,
               AVG(structure_score) as avg_struct,
               AVG(rouge1_f) as avg_r1,
               AVG(sentiment_match) as accuracy,
               AVG(judge_average) as avg_judge,
               COUNT(judge_average) as judge_samples
        FROM eval_results
        GROUP BY model_name
    """)
    rows = cursor.fetchall()
    
    if not rows:
        print("No evaluation results found in database. Please run evaluation for at least one model first.")
        conn.close()
        return
        
    headers = ["Model Name", "Total Eval", "Structure Score", "ROUGE-1 F1", "Sentiment Acc", "GPT-Judge (Avg)", "Judge Samples"]
    table_data = []
    
    models = {}
    for r in rows:
        name, count, struct, r1, acc, judge, judge_cnt = r
        table_data.append([
            name, count, f"{struct:.3f}", f"{r1:.3f}", f"{acc*100:.1f}%", 
            f"{judge:.2f}/5.0" if judge is not None else "N/A", judge_cnt
        ])
        models[name] = {
            "structure_score": struct,
            "rouge1_f": r1,
            "accuracy": acc,
            "judge_avg": judge
        }
        
    print(tabulate(table_data, headers=headers, tablefmt="github"))
    print()
    
    # If we have both models, perform Go/No-Go check
    ft_model = os.environ.get("OLLAMA_FT_MODEL_NAME", "sentiment-analyst-ft")
    # Search for an entry containing 'sentiment-analyst-ft' or similar
    ft_key = None
    base_key = None
    for k in models.keys():
        if "ft" in k or "finetuned" in k or k == ft_model:
            ft_key = k
        else:
            base_key = k
            
    if ft_key:
        print(f"Evaluating Fine-Tuned model '{ft_key}' against Go/No-Go thresholds:")
        passed_all = True
        metrics_status = {}
        
        for metric, limit in GO_NO_GO_LIMITS.items():
            ft_val = models[ft_key].get(metric)
            if ft_val is None:
                metrics_status[metric] = ("N/A", "🟡 (No data)")
                continue
                
            if metric == "accuracy":
                ft_disp = f"{ft_val*100:.1f}%"
                limit_disp = f"{limit*100:.1f}%"
                passed = ft_val >= limit
            else:
                ft_disp = f"{ft_val:.3f}"
                limit_disp = f"{limit:.3f}"
                passed = ft_val >= limit
                
            if passed:
                status = "✅ PASSED"
            else:
                status = "❌ FAILED"
                passed_all = False
                
            metrics_status[metric] = (ft_disp, f"{status} (Threshold: >= {limit_disp})")
            
        for metric, (val, stat) in metrics_status.items():
            print(f"  - {metric.replace('_', ' ').title()}: {val} -> {stat}")
            
        print()
        
        # Check if fine-tuned is better than baseline
        is_better = True
        if base_key:
            print(f"Comparing '{ft_key}' directly with Baseline '{base_key}':")
            for metric in GO_NO_GO_LIMITS.keys():
                ft_val = models[ft_key].get(metric)
                base_val = models[base_key].get(metric)
                if ft_val is not None and base_val is not None:
                    diff = ft_val - base_val
                    if metric == "accuracy":
                        diff_str = f"+{diff*100:.1f}%" if diff >= 0 else f"{diff*100:.1f}%"
                        ft_disp = f"{ft_val*100:.1f}%"
                        base_disp = f"{base_val*100:.1f}%"
                    else:
                        diff_str = f"+{diff:.3f}" if diff >= 0 else f"{diff:.3f}"
                        ft_disp = f"{ft_val:.3f}"
                        base_disp = f"{base_val:.3f}"
                    status = "📈 Better" if diff > 0 else ("📉 Worse" if diff < 0 else "⚖️ Equal")
                    print(f"  - {metric.replace('_', ' ').title()}: FT ({ft_disp}) vs Base ({base_disp}) -> {status} ({diff_str})")
                    if diff < 0:
                        is_better = False
            print()
            
        if passed_all and is_better:
            print("🎉 GO/NO-GO RESULT: GO (APPROVE FOR DEPLOYMENT) ✅")
            print("The fine-tuned model has successfully met all performance targets and outperformed the baseline.")
        else:
            print("⚠️ GO/NO-GO RESULT: NO-GO (DO NOT DEPLOY) ❌")
            print("The fine-tuned model failed to meet all requirements or performed worse than the baseline.")
            print("\n=======================================================")
            print("ROOT CAUSE DIAGNOSIS & PLAYBOOK")
            print("=======================================================")
            
            # Diagnose root causes based on metrics
            failed_metrics = []
            for metric, limit in GO_NO_GO_LIMITS.items():
                ft_val = models[ft_key].get(metric)
                if ft_val is not None and ft_val < limit:
                    failed_metrics.append(metric)
                    
            if base_key and models[ft_key].get("accuracy") is not None and models[base_key].get("accuracy") is not None:
                if models[ft_key]["accuracy"] < models[base_key]["accuracy"]:
                    failed_metrics.append("accuracy_regression")
                    
            print("\nDetected Symptoms & Solutions:")
            for symptom in failed_metrics:
                if symptom == "accuracy_regression":
                    print("🚨 Regression: FT accuracy is lower than baseline!")
                    print("  -> Root Cause: Catastrophic forgetting or incorrect dataset format.")
                    print("  -> Playbook Level 3: Verify ChatML structure in 02_prepare_dataset.py. Reduce training epochs or lower learning rate.")
                elif symptom == "structure_score":
                    print("🚨 Structure score is below 0.80!")
                    print("  -> Root Cause: Output formatting rules were not fully integrated, or LoRA rank is too low.")
                    print("  -> Playbook Level 2: Increase LoRA rank to r=32 / alpha=64. Filter golden responses to ensure they strictly contain all sections.")
                elif symptom == "accuracy":
                    print("🚨 Sentiment accuracy is below 70%!")
                    print("  -> Root Cause: Sentiment skew or lack of representative training examples.")
                    print("  -> Playbook Level 4: Balance the dataset's sentiment distribution in 01_collect_data.py.")
                elif symptom == "rouge1_f":
                    print("🚨 ROUGE-1 F1 score is below 0.35!")
                    print("  -> Root Cause: Token lengths are heavily mismatched, or vocabulary of golden response is too complex.")
                    print("  -> Playbook Level 3: Check average prompt length and lower output temperature in teacher model generation.")
                elif symptom == "judge_avg":
                    print("🚨 GPT-Judge average score is below 3.0/5.0!")
                    print("  -> Root Cause: Model outputs lack detailed evidence or trading signal nuance.")
                    print("  -> Playbook Level 2: Enhance prompts in teacher model to include explicit logic. Add manual examples.")
                    
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Baseline or Fine-tuned models on test dataset")
    parser.add_argument("--model", type=str, default=None, help="Name of model to evaluate (in Ollama)")
    parser.add_argument("--limit", type=int, default=None, help="Limit test samples to evaluate")
    parser.add_argument("--compare", action="store_true", help="Compare evaluation results of all models in SQLite")
    args = parser.parse_args()
    
    if args.compare:
        compare_models()
    elif args.model:
        evaluate_model(args.model, limit=args.limit)
    else:
        parser.print_help()
