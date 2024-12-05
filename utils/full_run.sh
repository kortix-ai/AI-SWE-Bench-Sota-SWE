# lite: 300
# verified: 500
python swe_runner.py --range 1 40 --dataset-type lite --max-iterations 12 --model-name "sonnet" --execute-file agent/agent_state2.py --run-eval --num-worker 6 --install-packages --submission --disable-streamlit  > full_run.log 2>&1 &

tail -f full_run.log