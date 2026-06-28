#!/bin/bash
set -e

# Run baseline model evaluation (all 144 samples)
echo "=== Starting evaluation of baseline model (qwen3:4b) ==="
conda run -n finetune python finetune/scripts/04_evaluate.py --model qwen3:4b

# Run fine-tuned model evaluation (all 144 samples)
echo "=== Starting evaluation of fine-tuned model (sentiment-analyst-ft) ==="
conda run -n finetune python finetune/scripts/04_evaluate.py --model sentiment-analyst-ft

# Print comparison
echo "=== Generating final comparison report ==="
conda run -n finetune python finetune/scripts/04_evaluate.py --compare
