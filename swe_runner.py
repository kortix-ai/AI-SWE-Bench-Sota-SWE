import argparse
import subprocess
import os
import sys
import time

def main():
    parser = argparse.ArgumentParser(description='SWE Runner')
    parser.add_argument("--num-examples", type=int, default=1,
                        help="Number of examples to test (default: 1)")
    parser.add_argument("--test-index", type=int,
                        help="Run a specific test by index (starting from 1)")
    parser.add_argument("--range", nargs=2, type=int, metavar=('START', 'END'),
                        help="Run tests from START to END index (inclusive)")
    parser.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite",
                        help="Dataset to use (default: princeton-nlp/SWE-bench_Lite)")
    parser.add_argument("--split", default="test",
                        help="Dataset split to use (default: test)")
    parser.add_argument("--track-files", nargs="+",
                        help="List of files and/or folders to track")
    parser.add_argument("--output-dir", default="./outputs",
                        help="Directory to save outputs (default: ./outputs)")
    parser.add_argument("--join-only", action="store_true",
                        help="Only join existing JSON files to JSONL, skip running tests")
    parser.add_argument('--timeout', type=int, default=1800,
                        help='Timeout for evaluation in seconds')
    parser.add_argument('--num-workers', type=int, default=1,
                        help='Number of parallel workers')
    args = parser.parse_args()

    # Start the Streamlit app
    print("Starting Streamlit app...")
    streamlit_cmd = ["streamlit", "run", "streamlit_runner.py", "--", "--output-dir", args.output_dir]
    streamlit_process = subprocess.Popen(streamlit_cmd)

    try:
        # Run inference.py
        print("Running inference...")
        inference_cmd = [sys.executable, "inference.py"]
        if args.test_index:
            inference_cmd += ["--test-index", str(args.test_index)]
        elif args.range:
            inference_cmd += ["--range", str(args.range[0]), str(args.range[1])]
        else:
            inference_cmd += ["--num-examples", str(args.num_examples)]
        inference_cmd += ["--dataset", args.dataset]
        inference_cmd += ["--split", args.split]
        inference_cmd += ["--output-dir", args.output_dir]
        if args.track_files:
            inference_cmd += ["--track-files"] + args.track_files
        if args.join_only:
            inference_cmd += ["--join-only"]
        subprocess.run(inference_cmd, check=True)

        # Run evaluation.py
        print("Running evaluation...")
        combined_output_files = [f for f in os.listdir(args.output_dir) if f.startswith('__combined_agentpress_output_') and f.endswith('.jsonl')]
        if combined_output_files:
            input_file = os.path.join(args.output_dir, combined_output_files[0])
        else:
            print("No combined output file found.")
            sys.exit(1)
        evaluation_cmd = [
            sys.executable, "evaluation.py",
            "--input-file", input_file,
            "--output-dir", args.output_dir,
            "--dataset", args.dataset,
            "--split", args.split,
            "--timeout", str(args.timeout),
            "--num-workers", str(args.num_workers)
        ]
        subprocess.run(evaluation_cmd, check=True)

        # Wait for user to close Streamlit app
        print("Press Ctrl+C to stop Streamlit app.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping Streamlit app...")
    finally:
        streamlit_process.terminate()
        streamlit_process.wait()
        print("Streamlit app stopped.")

if __name__ == "__main__":
    main()