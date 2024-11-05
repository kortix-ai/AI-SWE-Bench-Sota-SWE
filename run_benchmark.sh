#!/bin/bash

# Run the inference script
python run_infer.py --num-examples 5 --agent-dir ./agent

# Combine outputs into a single JSONL file
mkdir -p outputs
jq -c '.' outputs/*.json > outputs/output.jsonl

# Run the evaluation (assuming you have the evaluation script set up)
# Replace 'evaluation_script.py' with the actual evaluation script provided by SWE-Bench
# python evaluation_script.py --predictions outputs/output.jsonl --output results.json
