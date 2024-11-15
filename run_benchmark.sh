#!/bin/bash

# Lite:  300 testcases => --range 1 300

python swe_runner.py --range 1 1 --dataset-type lite --max-iterations 35 --run-eval --model-name "sonnet" #--no-archive


# Verified:  500 testcases

# python swe_runner.py --range 1 2 --dataset-type verified --max-iterations 20 --run-eval --model-name "sonnet" --no-archive


# "Swing" testcases (that either openhands | Claude Tools success) => should success these testcases to win %

python swe_runner.py --range 1 1 --instances-file utils/diff_claude_openhands.json --dataset-type verified --max-iterations 35 --run-eval --model-name "sonnet" #--num-worker 3 #--no-archive
