import argparse
import subprocess
import os
import sys
import json
import tempfile
import shutil
from datasets import load_dataset
import pandas as pd
from multiprocessing import Pool
from tqdm import tqdm

def get_instance_docker_image(instance_id: str) -> str:
    """Get the docker image name for a specific instance."""
    DOCKER_IMAGE_PREFIX = os.environ.get('EVAL_DOCKER_IMAGE_PREFIX', 'docker.io/xingyaoww/')
    image_name = 'sweb.eval.x86_64.' + instance_id
    image_name = image_name.replace('__', '_s_')  # To comply with Docker naming conventions
    return (DOCKER_IMAGE_PREFIX.rstrip('/') + '/' + image_name).lower()

def start_docker_container(instance, track_files, install_packages=False):
    """
    Start the Docker container and keep it running.
    Returns the container name.
    """
    instance_id = instance['instance_id']
    container_name = f'swe_runner_{instance_id}'

    try:
        subprocess.run(['docker', 'rm', '-f', container_name], check=True)
        print(f"\nRemoved existing container '{container_name}'")
    except subprocess.CalledProcessError:
        pass

    docker_image = get_instance_docker_image(instance_id)
    print(f"Using Docker image: {docker_image}")

    print("\nPulling Docker image...")
    subprocess.run(['docker', 'pull', docker_image], check=True)

    cmd = [
        'docker', 'run', 
        '--name', container_name,
        '-d',  # Detached mode
        '-e', f'SWE_INSTANCE_ID={instance_id}',
        '-e', f'TRACK_FILES={" ".join(track_files) if track_files else ""}',
        docker_image,
        '/bin/bash', '-c',
        (
            '. /opt/miniconda3/etc/profile.d/conda.sh && '
            'conda activate testbed && '
            'tail -f /dev/null'
        )
    ]

    print("\nStarting Docker container...")
    subprocess.run(cmd, check=True)

    print(f"Docker container '{container_name}' started and is running.")

    if install_packages:
        installation_commands = '''
source /opt/miniconda3/bin/activate
conda activate testbed
cd /testbed

sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen
locale-gen

export LANG=en_US.UTF-8
export LANGUAGE=en_US:en
export LC_ALL=en_US.UTF-8

git config --global --add safe.directory /testbed
python -m pip install pytest
python -m pip install -e '.[test]'
'''
        result = execute_command_in_container(container_name, installation_commands)
        if result.returncode != 0:
            print(f"Error installing packages in container '{container_name}':\n{result.stderr}")
            sys.exit(1)
        else:
            print(f"Packages installed successfully in container '{container_name}'.")

    return container_name

def stop_docker_container(container_name):
    """
    Stop and remove the Docker container.
    """
    print(f"\nStopping and removing Docker container '{container_name}'...")
    try:
        subprocess.run(['docker', 'stop', container_name], check=True)
        subprocess.run(['docker', 'rm', container_name], check=True)
        print(f"Docker container '{container_name}' stopped and removed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error stopping/removing container: {e}", file=sys.stderr)

def execute_command_in_container(container_name, command):
    """
    Execute a command inside the running Docker container and return the output.
    """
    full_command = f'. /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && {command}'
    cmd = ['docker', 'exec', container_name, 'bash', '-c', full_command]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result

def extract_tracked_files(container_name, track_files, output_dir):
    """
    Extract tracked files directly from container to output directory.
    """
    if not track_files:
        return
        
    os.makedirs(output_dir, exist_ok=True)
    for file_path in track_files:
        # Remove leading slash and create target directory
        rel_path = file_path.lstrip('/')
        target_dir = os.path.join(output_dir, os.path.dirname(rel_path))
        os.makedirs(target_dir, exist_ok=True)
        
        # Copy file from container to output directory
        try:
            subprocess.run(
                ['docker', 'cp', f'{container_name}:{file_path}', os.path.join(output_dir, rel_path)], 
                check=True
            )
        except subprocess.CalledProcessError:
            print(f"Warning: Failed to copy {file_path} from container", file=sys.stderr)

def convert_outputs_to_jsonl(output_dir: str) -> str:
    """Convert json outputs to SWE-bench jsonl format and combine them, skipping files > 1MB"""
    all_data = []
    MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB in bytes

    print(f"\nSearching for JSON files in {output_dir}...")

    for instance_dir in os.listdir(output_dir):
        instance_path = os.path.join(output_dir, instance_dir)

        if not os.path.isdir(instance_path):
            continue

        json_file = os.path.join(instance_path, f'{instance_dir}.json')

        if os.path.exists(json_file):
            # Check file size before processing
            file_size = os.path.getsize(json_file)
            if file_size > MAX_FILE_SIZE:
                print(f"Skipping {json_file} - file size {file_size/1024/1024:.2f}MB exceeds 1MB limit")
                continue
                
            # Read input file
            with open(json_file) as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = [data]
                all_data.extend(data)

    if all_data:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_output = os.path.join(output_dir, f'__combined_agentpress_output_{timestamp}_{len(all_data)}.jsonl')
        with open(combined_output, 'w') as f:
            for item in all_data:
                f.write(json.dumps(item) + '\n')
        print(f'Created combined output file: {combined_output}')
        return combined_output  # Return the path of the combined output file
    else:
        print("\nNo data found to combine")
        return ""

def is_instance_id_list(value):
    """Check if a list contains what appears to be instance IDs."""
    if not isinstance(value, list) or not value:
        return False
    # Check if list contains strings with common instance ID patterns
    return all(isinstance(x, str) and ('__' in x or '_' in x) for x in value)

def find_instance_ids(data):
    """Recursively search through JSON data for instance IDs."""
    if isinstance(data, dict):
        for value in data.values():
            result = find_instance_ids(value)
            if result:
                return result
    elif isinstance(data, list):
        if is_instance_id_list(data):
            return data
        for item in data:
            result = find_instance_ids(item)
            if result:
                return result
    return []

def get_instance_ids_from_file(file_path):
    """Load instance IDs from a JSON file."""
    with open(file_path) as f:
        data = json.load(f)
        return find_instance_ids(data)

def main():
    parser = argparse.ArgumentParser()
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
    parser.add_argument("--max-iterations", type=int, default=10,
                        help="Maximum number of iterations")
    parser.add_argument("--model-name", choices=["sonnet", "haiku", "deepseek", "gpt-4o", "qwen"], default="sonnet",
                        help="Model name to use (choices: sonnet, haiku, deepseek)")
    parser.add_argument('--num-workers', type=int, default=1,
                        help='Number of parallel workers')
    parser.add_argument("--execute-file", default="agent/agent.py",
                        help="Path to the script to execute (default: agent/agent.py)")
    parser.add_argument("--install-packages", action="store_true", default=False,
                        help="Install packages inside Docker container (default: False)")
    parser.add_argument("--run_id", default="KortixAI",
                        help="Identifier for the run, name of model (default: KortixAI)")
    parser.add_argument("--submission", action="store_true", default=False,
                        help="Enable submission mode to generate files in SWE-bench format")
    dataset_group = parser.add_argument_group('Dataset Options')
    dataset_group.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite",
                               help="Dataset to use (default: princeton-nlp/SWE-bench_Lite)")
    dataset_group.add_argument("--dataset-type", choices=["lite", "verified"],
                               help="Type of dataset to use: 'lite' for SWE-bench_Lite, 'verified' for SWE-bench_Verified")
    args = parser.parse_args()

    if args.dataset_type:
        dataset_mapping = {
            "lite": "princeton-nlp/SWE-bench_Lite",
            "verified": "princeton-nlp/SWE-bench_Verified"
        }
        args.dataset = dataset_mapping[args.dataset_type]

    if args.join_only:
        print("Join-only mode: combining existing JSON files...")
        convert_outputs_to_jsonl(args.output_dir)
        return

    # Load dataset
    print(f"Loading dataset {args.dataset} ({args.split})...")
    dataset = load_dataset(args.dataset, split=args.split)

    # Select instances based on arguments
    if args.instance_id is not None:
        instances = dataset.filter(lambda x: x['instance_id'] == args.instance_id)
    elif args.instances_file is not None:
        instance_ids = get_instance_ids_from_file(args.instances_file)
        instances = dataset.filter(lambda x: x['instance_id'] in instance_ids)
    elif args.test_index is not None:
        if args.test_index < 1 or args.test_index > len(dataset):
            raise ValueError(f"Test index must be between 1 and {len(dataset)}")
        instances = dataset.select([args.test_index - 1])  # Convert to 0-based index
    elif args.range is not None:
        start_index, end_index = args.range
        if start_index < 1 or end_index > len(dataset) or start_index > end_index:
            raise ValueError(f"Start index must be >= 1 and end index must be <= {len(dataset)} and start must be <= end")
        instances = dataset.select(range(start_index - 1, end_index))  # Convert to 0-based index
    else:
        instances = dataset.select(range(min(args.num_examples, len(dataset))))

    os.makedirs(args.output_dir, exist_ok=True)

    # Convert instances to a list
    instances = list(instances)

    os.makedirs(args.output_dir, exist_ok=True)

    # Create list of (args, instance) tuples
    args_instance_list = [(args, instance) for instance in instances]

    total_instances = len(args_instance_list)
    pbar = tqdm(total=total_instances, desc='Instances processed')

    if args.num_workers > 1:
        with Pool(args.num_workers) as pool:
            results = pool.imap_unordered(process_instance, args_instance_list)
            for _ in results:
                pbar.update(1)
    else:
        for args_instance in args_instance_list:
            process_instance(args_instance)
            pbar.update(1)

    combined_output_file = convert_outputs_to_jsonl(args.output_dir)

    if args.submission:
        # Step 1 and 2: Create submissions directory and run_id directory
        submissions_dir = 'submissions'
        os.makedirs(submissions_dir, exist_ok=True)
        run_id_dir = os.path.join(submissions_dir, args.run_id)
        os.makedirs(run_id_dir, exist_ok=True)

        # Step 0: Copy or create README.md and metadata.yml
        utils_dir = 'utils'
        for file_name in ['README.md', 'metadata.yml']:
            src_file = os.path.join(utils_dir, file_name)
            dest_file = os.path.join(run_id_dir, file_name)
            
            if os.path.exists(src_file):
                shutil.copy(src_file, dest_file)
                print(f"Copied {file_name} from utils/ to {dest_file}")
            else:
                # Create empty file if source doesn't exist
                with open(dest_file, 'w') as f:
                    pass
                print(f"Created empty {file_name} at {dest_file}")

        # Step 4: Copy the combined output file to submissions/run_id as all_preds.jsonl
        dest_combined_output_file = os.path.join(run_id_dir, 'all_preds.jsonl')
        if combined_output_file and os.path.exists(combined_output_file):
            shutil.copy(combined_output_file, dest_combined_output_file)
            print(f"Copied combined output to {dest_combined_output_file}")
        else:
            print("Combined output file not found. Skipping copy.")
            return

        # Step 5: Create trajs directory
        trajs_dir = os.path.join(run_id_dir, 'trajs')
        os.makedirs(trajs_dir, exist_ok=True)

        # Step 6: Copy trajectory files to submissions/run_id/trajs
        for instance_dir in os.listdir(args.output_dir):
            threads_dir = os.path.join(args.output_dir, instance_dir, 'threads')
            if os.path.exists(threads_dir):
                for file_name in os.listdir(threads_dir):
                    if file_name.endswith('_history.json'):
                        src_file = os.path.join(threads_dir, file_name)
                        dest_file = os.path.join(trajs_dir, f'{instance_dir}.json')
                        shutil.copy(src_file, dest_file)
                        print(f"Copied trajectory for instance {instance_dir} to {dest_file}")
                        break
            else:
                print(f"Threads directory for instance {instance_dir} not found.")

        # Step 7: Run evaluation using the specified command
        evaluation_cmd = [
            sys.executable, '-m', 'swebench.harness.run_evaluation',
            '--dataset_name', args.dataset,
            '--predictions_path', dest_combined_output_file,
            '--max_workers', str(args.num_workers),
            '--run_id', args.run_id
        ]
        print("Running evaluation...")
        subprocess.run(evaluation_cmd, check=True)
        print("Evaluation completed.")

        # Step 8: Copy logs to submissions/run_id/logs
        source_log_dir = os.path.join('logs', 'run_evaluation', args.run_id, args.run_id)
        dest_log_dir = os.path.join(run_id_dir, 'logs')
        os.makedirs(dest_log_dir, exist_ok=True)
        if os.path.exists(source_log_dir):
            for instance_dir in os.listdir(source_log_dir):
                instance_log_dir = os.path.join(source_log_dir, instance_dir)
                if os.path.isdir(instance_log_dir):
                    dest_instance_log_dir = os.path.join(dest_log_dir, instance_dir)
                    shutil.copytree(instance_log_dir, dest_instance_log_dir, dirs_exist_ok=True)
            print(f"Copied logs to {dest_log_dir}")
        else:
            print(f"Source log directory {source_log_dir} not found.")

def process_instance(args_instance_tuple):
    args, instance = args_instance_tuple
    instance_id = instance['instance_id']

    # Create instance-specific output directory with index prefix
    instance_output_dir = os.path.join(args.output_dir, f"{instance_id}")
    os.makedirs(instance_output_dir, exist_ok=True)

    # Update output file paths to use instance-specific directory but keep original names
    output_file = os.path.join(instance_output_dir, f'{instance_id}.json')
    ground_truth_file = os.path.join(instance_output_dir, f'{instance_id}_ground_truth.json')
    log_file = os.path.join(instance_output_dir, f'{instance_id}.log')
    tracked_files_dir = os.path.join(instance_output_dir, 'files')

    # Remove instance directory if it exists
    if os.path.exists(instance_output_dir):
        subprocess.run(['rm', '-rf', instance_output_dir], check=True)
        os.makedirs(instance_output_dir)

    with open(ground_truth_file, 'w') as f:
        json.dump({'patch': instance['patch'], 'test_patch': instance['test_patch']}, f, indent=2)

    container_name = start_docker_container(instance, args.track_files or [], args.install_packages)
    try:
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            problem_file = f.name
            json.dump([instance], f)

        cmd = [
            sys.executable, args.execute_file,
            '--problem-file', problem_file,
            '--container-name', container_name,
            '--threads-dir', os.path.join(instance_output_dir, 'threads'),
            '--max-iterations', str(args.max_iterations),
            '--model-name', args.model_name,
        ]
        print(f"Running agent for instance {instance_id}...")
        result = subprocess.run(cmd, capture_output=True, text=True)

        with open(log_file, 'w') as f:
            f.write(result.stdout)
            f.write(result.stderr)

        if result.returncode != 0:
            print(f"Error running agent for instance {instance_id}:\n{result.stderr}")
            return

        if args.track_files:
            extract_tracked_files(container_name, args.track_files, os.path.join(instance_output_dir, 'files'))

        git_commands = f"""
mkdir -p /workspace/data &&
git config --global user.email "agent@example.com" && 
git config --global user.name "Agent" && 
git add -A && 
git commit -m "Agent modifications" || true && 
pwd && 
git diff --no-color {instance["base_commit"]} HEAD > /workspace/data/git_patch.diff
"""
        result_git = execute_command_in_container(container_name, git_commands)

        subprocess.run(['docker', 'cp', f'{container_name}:/workspace/data/git_patch.diff', os.path.join(instance_output_dir, f'{instance_id}.diff')], check=True)

        # Read the git_patch.diff
        git_patch_file = os.path.join(instance_output_dir, f'{instance_id}.diff')
        if os.path.exists(git_patch_file):
            with open(git_patch_file, 'r') as f:
                git_patch = f.read()
        else:
            git_patch = ""

        # Prepare the output data
        output = {
            "instance_id": instance_id,
            "model_patch": git_patch,
            "model_name_or_path": args.run_id
        }

        # Save the output to JSON file
        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"Saved output for instance {instance_id} to {output_file}")
        print(f"Saved logs for instance {instance_id} to {log_file}")

    finally:
        stop_docker_container(container_name)

if __name__ == "__main__":
    main()
