import argparse
import subprocess
import os
import sys
import time
import json
from inference import convert_outputs_to_jsonl

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
    test_selection_group.add_argument("--instances-file", type=str,
                                      help="JSON file containing list of instance IDs to run")
    
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
    parser.add_argument("--no-archive", dest='archive', action='store_false',
                        help="Do not archive the current outputs before running")
    parser.add_argument("--model-name", choices=["sonnet", "haiku", "deepseek", "gpt-4o", "qwen"], default="sonnet",
                        help="Model name to use (choices: sonnet, haiku, deepseek)")
    parser.add_argument("--run-eval", action="store_true", default=False,
                        help="Run evaluation step (default: False)")
    parser.add_argument("--only-eval", action="store_true", default=False,
                        help="Only run evaluation step, skip inference")
    parser.add_argument("--input-file", help="Path to the input file for evaluation")
    parser.add_argument("--execute-file", default="agent/agent.py",
                        help="Path to the script to execute (default: agent/agent.py)")
    parser.add_argument("--install-packages", action="store_true", default=False,
                        help="Install packages inside Docker container (default: False)")
    parser.add_argument("--run_id", default="KortixAI",
                        help="Identifier for the run, replaces YourModelName (default: KortixAI)")
    parser.add_argument("--submission", action="store_true", default=False,
                        help="Enable submission mode to generate files in SWE-bench format.")
    parser.add_argument("--rerun-failed", action="store_true", default=False,
                        help="Rerun inference and evaluation for failed instances")
    
    dataset_group = parser.add_argument_group('Dataset Options')
    dataset_group.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite",
                               help="Dataset to use (default: princeton-nlp/SWE-bench_Lite)")
    dataset_group.add_argument("--dataset-type", choices=["lite", "verified"],
                               help="Type of dataset to use: 'lite' for SWE-bench_Lite, 'verified' for SWE-bench_Verified")
    
    args = parser.parse_args()

    if args.rerun_failed:
        evaluation_results_file = os.path.join(args.output_dir, 'evaluation_results.jsonl')
        if not os.path.exists(evaluation_results_file):
            print(f"Evaluation results file not found at {evaluation_results_file}")
            sys.exit(1)
        
        failed_instance_ids = []
        successful_lines = []
        with open(evaluation_results_file, 'r') as f:
            lines = f.readlines()
        
        for line in lines:
            try:
                data = json.loads(line)
                instance_id = data['instance_id']
                test_result = data.get('test_result', {})
                report = test_result.get('report', {})
                # Determine if instance failed
                if report.get('resolved') == False or 'failed_apply_patch' in report or 'error_eval' in report or 'empty_generation' in report:
                    failed_instance_ids.append(instance_id)
                else:
                    successful_lines.append(line)
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON in evaluation_results.jsonl: {e}")
                continue

        if not failed_instance_ids:
            print("No failed instances found in evaluation_results.jsonl")
            sys.exit(0)
        
        # Write back the successful lines to evaluation_results.jsonl
        with open(evaluation_results_file, 'w') as f:
            f.writelines(successful_lines)
        
        # Write failed instance IDs to a file
        failed_instances_file = os.path.join(args.output_dir, 'failed_instances.json')
        with open(failed_instances_file, 'w') as f:
            json.dump(failed_instance_ids, f)
        
        # Set args.instances_file to failed_instances_file
        args.instances_file = failed_instances_file
        # Reset other instance selection arguments to avoid conflicts
        args.instance_id = None
        args.test_index = None
        args.range = None
        args.num_examples = None

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
        elif args.instances_file:
            inference_cmd += ["--instances-file", args.instances_file]
        elif args.test_index:
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
        if args.install_packages:
            inference_cmd += ["--install-packages"]
        inference_cmd += ["--max-iterations", str(args.max_iterations)]
        inference_cmd += ["--model-name", args.model_name]
        inference_cmd += ["--num-workers", str(args.num_workers)]
        inference_cmd += ["--execute-file", args.execute_file]
        inference_cmd += ["--run_id", args.run_id]
        if args.submission:
            inference_cmd += ["--submission"]
        subprocess.run(inference_cmd, check=True)

    if args.run_eval:
        # Skip evaluation if submission mode is enabled
        if args.submission:
            print("Skipping evaluation step - submission mode is enabled")
            sys.exit(0)
            
        # Run evaluation.py
        print("Running evaluation...")
        if args.input_file:
            input_file = args.input_file
        else:
            # Ensure outputs are combined before evaluation
            convert_outputs_to_jsonl(args.output_dir)
            # Find all combined output files and sort by timestamp (newest first)
            combined_output_files = [f for f in os.listdir(args.output_dir) 
                                   if f.startswith('__combined_agentpress_output_') 
                                   and f.endswith('.jsonl')]
            combined_output_files.sort(reverse=True)  # Newest first based on file name
            
            if combined_output_files:
                input_file = os.path.join(args.output_dir, combined_output_files[0])
                print(f"Using latest combined output file: {input_file}")
            else:
                print("No combined output file found. Please run inference first.")
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
