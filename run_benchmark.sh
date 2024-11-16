#!/bin/bash

# Lite:  300 testcases => --range 1 300

python swe_runner.py --range 203 205 --dataset-type lite --num-workers 3 --max-iterations 35 --run-eval --model-name "sonnet" #--no-archive


# Verified:  500 testcases

# python swe_runner.py --range 1 2 --dataset-type verified --max-iterations 20 --run-eval --model-name "sonnet" --no-archive


# "Swing" testcases (that either openhands | Claude Tools success) => should success these testcases to win %

# python swe_runner.py --instances-file utils/diff_claude_openhands.json --dataset-type verified --max-iterations 35 --run-eval --no-archive --num-worker 5 --model-name "sonnet" #--num-worker 3 #--no-archive

# python swe_runner.py --join-only --disable-streamlit --no-archive
# python evaluation.py --input-file outputs/__combined_agentpress_output_20241116_204926_4.jsonl --dataset princeton-nlp/SWE-bench_Verified