#!/bin/bash

# Lite:  300 testcases => --range 1 300

python swe_runner.py --range 1 6 --dataset-type lite --num-workers 6 --max-iterations 35 --run-eval --model-name "sonnet" #--no-archive


# Verified:  500 testcases

# python swe_runner.py --range 1 2 --dataset-type verified --max-iterations 20 --run-eval --model-name "sonnet" --no-archive


# "Swing" testcases (that either openhands | Claude Tools success) => should success these testcases to win %

python swe_runner.py --instances-file utils/diff_claude_openhands.json --dataset-type verified --max-iterations 35 --run-eval --no-archive --num-worker 5 --model-name "sonnet" #--num-worker 3 #--no-archive

python swe_runner.py --instances-file repo/swing_test_10.json  --dataset-type verified --max-iterations 25 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval --num-worker 5

python swe_runner.py --join-only --disable-streamlit --no-archive
python evaluation.py --input-file ./outputs/__combined_agentpress_output_20241117_002326_4.jsonl --dataset princeton-nlp/SWE-bench_Lite


# lite 
python swe_runner.py --instances-file repo/lite_4.json --dataset-type lite --max-iterations 32 --run-eval --num-worker 3 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py


python swe_runner.py --instance-id astropy__astropy-12907 --dataset-type lite --max-iterations 30 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval


python swe_runner.py --range 1 10 --dataset-type lite --max-iterations 30 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval --num-worker 4



python swe_runner.py --instance-id astropy__astropy-14508 --dataset-type verified --max-iterations 30 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval

python swe_runner.py --instances-file repo/swing_test_10.json --dataset-type verified --max-iterations 30 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval --no-archive --num-worker 3


python swe_runner.py --instances-file repo/swing_test_cases.json --dataset-type verified --max-iterations 30 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval --no-archive --num-worker 4



python swe_runner.py --instances-file repo/lite_4.json --dataset-type lite --max-iterations 40 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval --no-archive --num-worker 5 --install-packages



python swe_runner.py --instances-file repo/swing_test_cases.json --dataset-type verified --max-iterations 21 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval --no-archive --num-worker 5 --install-packages


# evaluation:
python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Lite \
    --predictions_path outputs/__combined_agentpress_output_20241119_165716_1.jsonl \
    --max_workers 1 \
    --run_id test_eval


python swe_runner.py --range 1 1 --dataset-type lite --max-iterations 31 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval --no-archive --num-worker 1 --install-packages --submission


# Run full for Lite
python swe_runner.py --range 1 300 --dataset-type lite --max-iterations 31 --model-name "sonnet" --execute-file agent/agent_with_state_reset.py --run-eval --no-archive --num-worker 4 --install-packages --submission