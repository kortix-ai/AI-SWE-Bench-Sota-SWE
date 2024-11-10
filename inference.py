import argparse
import subprocess
import os
import sys
import json
import tempfile
from datasets import load_dataset
import pandas as pd 

def get_instance_docker_image(instance_id: str) -> str:
    """Get the docker image name for a specific instance."""
    DOCKER_IMAGE_PREFIX = os.environ.get('EVAL_DOCKER_IMAGE_PREFIX', 'docker.io/xingyaoww/')
    image_name = 'sweb.eval.x86_64.' + instance_id
    image_name = image_name.replace('__', '_s_')  # To comply with Docker naming conventions
    return (DOCKER_IMAGE_PREFIX.rstrip('/') + '/' + image_name).lower()

def start_docker_container(instance, track_files):
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

def convert_outputs_to_jsonl(output_dir: str):
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
        combined_output = os.path.join(output_dir, f'__combined_agentpress_output_{len(all_data)}.jsonl')
        with open(combined_output, 'w') as f:
            for item in all_data:
                f.write(json.dumps(item) + '\n')
        print(f'Created combined output file: {combined_output}')
    else:
        print("\nNo data found to combine")

def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--num-examples", type=int, default=1,
                        help="Number of examples to test (default: 1)")
    group.add_argument("--test-index", type=int,
                        help="Run a specific test by index (starting from 1)")
    group.add_argument("--range", nargs=2, type=int, metavar=('START', 'END'),
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
    parser.add_argument("--max-iterations", type=int, default=7,
                        help="Maximum number of iterations")
    args = parser.parse_args()

    if args.join_only:
        print("Join-only mode: combining existing JSON files...")
        convert_outputs_to_jsonl(args.output_dir)
        return

    # Load dataset
    print(f"Loading dataset {args.dataset} ({args.split})...")
    dataset = load_dataset(args.dataset, split=args.split)

    # Select instances based on arguments
    if args.test_index is not None:
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

    print(f"\nWill test {len(instances)} instances:")
    for idx, instance in enumerate(instances, 1):
        instance_id = instance['instance_id']

        # Create instance-specific output directory with index prefix
        instance_output_dir = os.path.join(args.output_dir, f"{instance_id}")
        os.makedirs(instance_output_dir, exist_ok=True)

        # Update output file paths to use instance-specific directory but keep original names
        output_file = os.path.join(instance_output_dir, f'{instance_id}.json')
        log_file = os.path.join(instance_output_dir, f'{instance_id}.log')
        tracked_files_dir = os.path.join(instance_output_dir, 'files')

        # Remove instance directory if it exists
        if os.path.exists(instance_output_dir):
            subprocess.run(['rm', '-rf', instance_output_dir], check=True)
            os.makedirs(instance_output_dir)

        container_name = start_docker_container(instance, args.track_files or [])

        try:
            with tempfile.NamedTemporaryFile('w', delete=False) as f:
                problem_file = f.name
                json.dump([instance], f)

            cmd = [
                sys.executable, 'agent/agent.py',
                '--problem-file', problem_file,
                '--container-name', container_name,
                '--threads-dir', os.path.join(instance_output_dir, 'threads'),
                '--max-iterations', str(args.max_iterations)
            ]
            print("Running agent...")
            result = subprocess.run(cmd, capture_output=True, text=True)

            with open(log_file, 'w') as f:
                f.write(result.stdout)
                f.write(result.stderr)

            if result.returncode != 0:
                print(f"Error running agent for instance {instance_id}:\n{result.stderr}")
                continue

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
                "model_name_or_path": "YourModelName"  # Replace with actual model name if available
            }

            # Save the output to JSON file
            with open(output_file, 'w') as f:
                json.dump(output, f, indent=2)

            print(f"Saved output for instance {instance_id} to {output_file}")
            print(f"Saved logs for instance {instance_id} to {log_file}")

        finally:
            stop_docker_container(container_name)

    convert_outputs_to_jsonl(args.output_dir)

if __name__ == "__main__":
    main()