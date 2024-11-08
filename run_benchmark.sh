#!/bin/bash

# Run the inference script
# --num-examples
python swe_runner.py \
    --test-index 6 \
    --track-files /tmp/agentpress/ 
    # --streamlit

# python swe_runner.py \
#     --range 3 6 \
#     --agent-dir ./agent \
#     --track-files /tmp/agentpress/ \
    # --streamlit

# Combine outputs into a single JSONL file
# mkdir -p outputs
# jq -c '.' outputs/*.json > outputs/output.jsonl

# Run the evaluation (assuming you have the evaluation script set up)
# Replace 'evaluation_script.py' with the actual evaluation script provided by SWE-Bench
# python evaluation_script.py --predictions outputs/output.jsonl --output results.json
