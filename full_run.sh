python swe_runner.py --range 1 1 --dataset-type lite --max-iterations 20 --model-name "sonnet" \
 --execute-file agent/agent_with_state_reset.py --run-eval --no-archive --num-worker 1 --install-packages > full_run.log 2>&1 &

tail -f full_run.log