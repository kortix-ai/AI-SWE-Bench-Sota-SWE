import argparse
import subprocess
import os
import sys
import time

def main():
    parser = argparse.ArgumentParser(description='SWE Runner')
    
    test_selection_group = parser.add_argument_group('Test Selection')
    test_selection_group.add_argument("--num-examples", type=int, default=1,
                                      help="Number of examples to test (default: 1)")
    test_selection_group.add_argument("--test-index", type=int,
                                      help="Run a specific test by index (starting from 1)")
    test_selection_group.add_argument("--range", nargs=2, type=int, metavar=('START', 'END'),
                                      help="Run tests from START to END index (inclusive)")
    test_selection_group.add_argument("--instance-id", type=str,
                                      help="Choose a specific instance by instance_id")
    
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
    parser.add_argument("--max-iterations", type=int, default=10,
                        help="Maximum number of iterations")
    parser.add_argument("--disable-streamlit", action="store_true",
                        help="Disable the Streamlit app")
    parser.add_argument("--archive", action="store_true", default=True,
                        help="Archive the current outputs before running")
    parser.add_argument("--model-name", choices=["sonnet", "haiku", "deepseek", "gpt-4o", "qwen"], default="sonnet",
                        help="Model name to use (choices: sonnet, haiku, deepseek)")
    parser.add_argument("--run-eval", action="store_true", default=False,
                        help="Run evaluation step (default: False)")
    parser.add_argument("--only-eval", action="store_true", default=False,
                        help="Only run evaluation step, skip inference")
    parser.add_argument("--input-file", help="Path to the input file for evaluation")
    
    dataset_group = parser.add_argument_group('Dataset Options')
    dataset_group.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite",
                               help="Dataset to use (default: princeton-nlp/SWE-bench_Lite)")
    dataset_group.add_argument("--dataset-type", choices=["lite", "verified"],
                               help="Type of dataset to use: 'lite' for SWE-bench_Lite, 'verified' for SWE-bench_Verified")
    
    args = parser.parse_args()
    
    if args.only_eval:
        args.run_eval = True

    if args.dataset_type:
        dataset_mapping = {
            "lite": "princeton-nlp/SWE-bench_Lite",
            "verified": "princeton-nlp/SWE-bench_Verified"
        }
        args.dataset = dataset_mapping[args.dataset_type]

    if args.archive and not args.only_eval:
        import shutil
        from datetime import datetime
        if os.path.exists(args.output_dir):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_dir = os.path.join("archives", f"{timestamp}_outputs")
            shutil.move(args.output_dir, archive_dir)
            os.makedirs(args.output_dir)

    streamlit_process = None
    if not args.disable_streamlit:
        from streamlit_runner import StreamlitRunner
        streamlit_process = StreamlitRunner()
        streamlit_process.run(args.output_dir)
        print("Streamlit app started for real-time visualization.")

    if not args.only_eval:
        # Run inference.py
        print("Running inference...")
        inference_cmd = [sys.executable, "inference.py"]
        if args.instance_id:
            inference_cmd += ["--instance-id", args.instance_id]
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
        inference_cmd += ["--max-iterations", str(args.max_iterations)]
        inference_cmd += ["--model-name", args.model_name]
        subprocess.run(inference_cmd, check=True)

    if args.run_eval:
        # Run evaluation.py
        print("Running evaluation...")
        if args.input_file:
            input_file = args.input_file
        else:
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

    if not args.disable_streamlit:
        if streamlit_process:
            input("Type any key to stop streamlit !")
            streamlit_process.stop()
            print("Streamlit app stopped.")


if __name__ == "__main__":
    main()