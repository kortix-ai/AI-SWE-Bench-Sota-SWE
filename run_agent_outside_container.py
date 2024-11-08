import os
import sys
import json
import tempfile
import subprocess
import pandas as pd
from datasets import load_dataset
from typing import Any
import signal
import shlex

def get_instance_docker_image(instance_id: str) -> str:
    """Get the docker image name for a specific instance."""
    DOCKER_IMAGE_PREFIX = os.environ.get('EVAL_DOCKER_IMAGE_PREFIX', 'docker.io/xingyaoww/')
    image_name = 'sweb.eval.x86_64.' + instance_id
    image_name = image_name.replace('__', '_s_')  # To comply with Docker naming conventions
    return (DOCKER_IMAGE_PREFIX.rstrip('/') + '/' + image_name).lower()

def get_swebench_workspace_dir_name(instance: dict) -> str:
    """Get the properly formatted workspace directory name."""
    return f"{instance['repo']}__{instance['version']}".replace('/', '__')

def start_docker_container(instance, agent_dir, track_files):
    """
    Start the Docker container and keep it running.
    
    Returns the container ID and temporary directory path.
    """
    instance_id = instance['instance_id']
    workspace_dir = get_swebench_workspace_dir_name(instance)

    # Get Docker image for this instance
    docker_image = get_instance_docker_image(instance_id)
    print(f"Using Docker image: {docker_image}")

    # Pull the Docker image
    print("\nPulling Docker image...")
    subprocess.run(['docker', 'pull', docker_image], check=True)

    # Create temporary directory for test files
    temp_dir = tempfile.mkdtemp()

    # Save instance data
    problem_file = os.path.join(temp_dir, 'problem.json')
    with open(problem_file, 'w') as f:
        json.dump([instance], f)

    # Build the Docker run command
    cmd = [
        'docker', 'run', 
        '--name', f'swe_runner_{instance_id}',  # Unique container name per instance
        '-d',  # Detached mode
        '-v', f'{temp_dir}:/workspace/data',  # Mount instance data
        '-v', f'{os.path.abspath(agent_dir)}:/agent',  # Mount agent code
        '-e', f'SWE_INSTANCE_ID={instance_id}',
        '-e', 'PIP_CACHE_DIR=/root/.cache/pip',
        '-e', f'OPENAI_API_KEY={os.environ.get("OPENAI_API_KEY", "")}',
        '-e', f'ANTHROPIC_API_KEY={os.environ.get("ANTHROPIC_API_KEY", "")}',
        '-e', f'GROQ_API_KEY={os.environ.get("GROQ_API_KEY", "")}',
        '-e', f'LANGFUSE_PUBLIC_KEY={os.environ.get("LANGFUSE_PUBLIC_KEY", "")}',
        '-e', f'LANGFUSE_SECRET_KEY={os.environ.get("LANGFUSE_SECRET_KEY", "")}',
        '-e', f'TRACK_FILES={" ".join(track_files) if track_files else ""}',
        docker_image,
        '/bin/bash', '-c',
        (
            # Initialize Conda environment and keep the container running
            '. /opt/miniconda3/etc/profile.d/conda.sh && '
            'conda activate testbed && '
            # Install agent requirements
            # 'pip install -r /agent/requirements.txt || true && '
            # 'python /agent/agent.py '
            # f'--repo-path . '
            # f'--problem-file /workspace/data/problem.json && '
            # 'git config --global user.email "agent@example.com" && '
            # 'git config --global user.name "Agent" && '
            # 'git add -A && '
            # 'git commit -m "Agent modifications" || true && '
            # "pwd && "
            # f'git diff --no-color {instance["base_commit"]} HEAD > /workspace/data/git_patch.diff && '
            # f'if [ ! -z "$TRACK_FILES" ]; then tar czf /workspace/data/tracked_files.tar.gz -C / $(echo "$TRACK_FILES" | sed "s|^/||") 2>/dev/null || true; fi && '
            # Keep the container running with activated Conda environment
            'tail -f /dev/null'
        )
    ]

    print("\nStarting Docker container...")
    subprocess.run(cmd, check=True)

    print(f"Docker container 'swe_runner_{instance_id}' started and is running.")
    return f'swe_runner_{instance_id}', temp_dir

def stop_docker_container(container_name, temp_dir):
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
    finally:
        # Clean up temporary directory
        subprocess.run(['rm', '-rf', temp_dir])

def execute_command_in_container(container_name, command):
    """
    Execute a command inside the running Docker container and stream outputs.
    Automatically activates Conda environment before running the command.
    """
    # Wrap the user command with Conda activation
    full_command = f'. /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && {command}'
    
    # Use shlex to safely split the command
    cmd = ['docker', 'exec', container_name, 'bash', '-c', full_command]
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # Stream stdout and stderr
        def stream_output(stream, is_stderr=False):
            for line in iter(stream.readline, ''):
                if is_stderr:
                    print(line, file=sys.stderr, end='')
                else:
                    print(line, end='')
            stream.close()

        import threading

        stdout_thread = threading.Thread(target=stream_output, args=(process.stdout, False))
        stderr_thread = threading.Thread(target=stream_output, args=(process.stderr, True))
        stdout_thread.start()
        stderr_thread.start()
        stdout_thread.join()
        stderr_thread.join()

        return_code = process.wait()
        if return_code != 0:
            print(f"Command exited with return code {return_code}", file=sys.stderr)

    except Exception as e:
        print(f"Error executing command: {e}", file=sys.stderr)

def interactive_mode(instance, agent_dir, track_files):
    """
    Interactive mode to send commands to the Docker container.
    Commands are executed within the activated Conda environment.
    """
    container_name, temp_dir = start_docker_container(instance, agent_dir, track_files)

    # Define a shutdown handler
    def shutdown(signum, frame):
        stop_docker_container(container_name, temp_dir)
        sys.exit(0)

    # Register signal handlers for graceful termination
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("\nInteractive Docker Runner")
    print("Type your commands below. Type 'exit' or 'quit' to terminate.\n")

    while True:
        try:
            # Prompt user for input
            user_input = input(">> ")

            if user_input.strip().lower() in ['exit', 'quit']:
                shutdown(None, None)

            if user_input.strip() == "":
                continue  # Skip empty commands

            # Execute the command inside the Docker container with Conda environment activated
            execute_command_in_container(container_name, user_input)

        except EOFError:
            # Handle Ctrl+D
            shutdown(None, None)
        except Exception as e:
            print(f"An error occurred: {e}", file=sys.stderr)

def load_and_test_instances(num_examples: int = 1, test_index: int = None, start_index: int = None, end_index: int = None, dataset_name: str = "princeton-nlp/SWE-bench_Lite", split: str = "test", agent_dir: str = "./agent", output_dir: str = "./outputs", track_files: list = None, no_stream: bool = False, interactive: bool = False):
    """
    Load and test the first N instances from the dataset using Docker.

    Args:
        num_examples: Number of examples to test (default: 1)
        dataset_name: Name of the dataset to load from
        split: Dataset split to use
        agent_dir: Path to your agent directory
        output_dir: Directory to save outputs
        track_files: List of files and/or folders to track and copy to outputs directory
        no_stream: Disable real-time output streaming
        interactive: Enable interactive mode
    """
    # Load dataset
    print(f"Loading dataset {dataset_name} ({split})...")
    dataset = load_dataset(dataset_name, split=split)

    # Select instances based on various selection criteria
    if test_index is not None:
        if test_index < 1 or test_index > len(dataset):
            raise ValueError(f"Test index must be between 1 and {len(dataset)}")
        instances = dataset.select([test_index - 1])  # Convert to 0-based index
    elif start_index is not None and end_index is not None:
        if start_index < 1 or end_index > len(dataset) or start_index > end_index:
            raise ValueError(f"Start index must be >= 1 and end index must be <= {len(dataset)} and start must be <= end")
        instances = dataset.select(range(start_index - 1, end_index))  # Convert to 0-based index
    else:
        instances = dataset.select(range(min(num_examples, len(dataset))))

    os.makedirs(output_dir, exist_ok=True)

    print(f"\nWill test {len(instances)} instances:")
    for idx, instance in enumerate(instances, 1):
        instance_id = instance['instance_id']
        workspace_dir = get_swebench_workspace_dir_name(instance)

        # Create instance-specific output directory with index prefix
        instance_output_dir = os.path.join(output_dir, f"{idx}_{instance_id}")
        os.makedirs(instance_output_dir, exist_ok=True)

        # Update output file paths to use instance-specific directory but keep original names
        output_file = os.path.join(instance_output_dir, f'{instance_id}.json')
        log_file = os.path.join(instance_output_dir, f'{instance_id}.log')
        tracked_files_dir = os.path.join(instance_output_dir, 'files')
        
        # Remove existing files if they exist
        if os.path.exists(output_file):
            os.remove(output_file)
        if os.path.exists(log_file):
            os.remove(log_file)
        if os.path.exists(tracked_files_dir):
            subprocess.run(['rm', '-rf', tracked_files_dir], check=True)

        print(f"\n{'='*50}")
        print(f"Testing instance {idx}/{len(instances)}: {instance_id}")
        print(f"Problem statement: {instance['problem_statement']}")
        print(f"Workspace directory: {workspace_dir}")
        print(f"{'='*50}\n")

        if interactive:
            # Enter interactive mode for this instance
            interactive_mode(instance, agent_dir, track_files)
            # After interactive mode, continue to next instance or terminate
            continue

        # Get Docker image for this instance
        docker_image = get_instance_docker_image(instance_id)
        print(f"Using Docker image: {docker_image}")

        # Pull the Docker image
        print("\nPulling Docker image...")
        subprocess.run(['docker', 'pull', docker_image], check=True)

        # Create temporary directory for test files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Save instance data
            problem_file = os.path.join(temp_dir, 'problem.json')
            with open(problem_file, 'w') as f:
                json.dump([instance], f)

            # Build the Docker run command
            print("Track files:", track_files)
            cmd = [
                'docker', 'run', 
                # '--rm', # disable now for debugging
                '-v', f'{temp_dir}:/workspace/data',  # Mount instance data
                '-v', f'{os.path.abspath(agent_dir)}:/agent',  # Mount agent code
                '-e', f'SWE_INSTANCE_ID={instance_id}',
                '-e', 'PIP_CACHE_DIR=/root/.cache/pip',
                '-e', f'OPENAI_API_KEY={os.environ.get("OPENAI_API_KEY", "")}',
                '-e', f'ANTHROPIC_API_KEY={os.environ.get("ANTHROPIC_API_KEY", "")}',
                '-e', f'GROQ_API_KEY={os.environ.get("GROQ_API_KEY", "")}',
                '-e', f'LANGFUSE_PUBLIC_KEY={os.environ.get("LANGFUSE_PUBLIC_KEY", "")}',
                '-e', f'LANGFUSE_SECRET_KEY={os.environ.get("LANGFUSE_SECRET_KEY", "")}',
                '-e', f'TRACK_FILES={" ".join(track_files) if track_files else ""}',
                docker_image,
                '/bin/bash', '-c',
                (
                    # Initialize Conda environment and keep the container running
                    '. /opt/miniconda3/etc/profile.d/conda.sh && '
                    'conda activate testbed && '
                    # Install agent requirements
                    'git config --global user.email "agent@example.com" && '
                    'git config --global user.name "Agent" && '
                    'git add -A && '
                    'git commit -m "Agent modifications" || true && '
                    f'git diff --no-color {instance["base_commit"]} HEAD > /workspace/data/git_patch.diff && '
                    f'if [ ! -z "$TRACK_FILES" ]; then tar czf /workspace/data/tracked_files.tar.gz -C / $(echo "$TRACK_FILES" | sed "s|^/||") 2>/dev/null || true; fi'
                )
            ]

            print("\nRunning test in Docker container...")
            if no_stream:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True
                )
                with open(log_file, 'w') as f:
                    f.write("=" * 50 + "\n")
                    f.write("OUTPUT:\n")
                    f.write("=" * 50 + "\n\n")
                    f.write(result.stdout)
                    f.write(result.stderr)
            else:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                stdout_output = []
                stderr_output = []

                with open(log_file, 'w') as f:
                    f.write("=" * 50 + "\n")
                    f.write("REAL-TIME OUTPUT:\n")
                    f.write("=" * 50 + "\n\n")
                    
                    while True:
                        stdout_line = process.stdout.readline()
                        stderr_line = process.stderr.readline()
                        
                        if stdout_line:
                            print(stdout_line, end='')  # Print to console
                            f.write(stdout_line)
                            f.flush()
                            stdout_output.append(stdout_line)
                        
                        if stderr_line:
                            print(stderr_line, end='', file=sys.stderr)  # Print to stderr
                            f.write(stderr_line)
                            f.flush()
                            stderr_output.append(stderr_line)
                        
                        if process.poll() is not None and not stdout_line and not stderr_line:
                            break

                result = type('Result', (), {
                    'returncode': process.returncode,
                    'stdout': ''.join(stdout_output),
                    'stderr': ''.join(stderr_output)
                })

            if result.returncode != 0:
                print(f"Error running agent for instance {instance_id}:\n{result.stderr}", file=sys.stderr)
                continue

            # Read the git patch from the temporary directory
            git_patch_file = os.path.join(temp_dir, 'git_patch.diff')
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

            # Save the output to JSON files
            output_file = os.path.join(output_dir, f'{instance_id}.json')
            log_file = os.path.join(output_dir, f'{instance_id}__log.txt')
            
            # Save the patch output
            with open(output_file, 'w') as f:
                json.dump(output, f, indent=2)
                
            # Save the stdout/stderr log in a readable format
            with open(log_file, 'w') as f:
                f.write("=" * 50 + "\n")
                f.write(f"RETURN CODE: {result.returncode}\n")
                f.write("=" * 50 + "\n\n")
                f.write("STDOUT:\n")
                f.write("=" * 50 + "\n")
                f.write(result.stdout)
                f.write("\n\nSTDERR:\n")
                f.write("=" * 50 + "\n")
                f.write(result.stderr)

            # Extract tracked files if they exist
            tracked_files_archive = os.path.join(temp_dir, 'tracked_files.tar.gz')
            if track_files and os.path.exists(tracked_files_archive):
                tracked_files_dir = os.path.join(instance_output_dir, 'files')
                os.makedirs(tracked_files_dir, exist_ok=True)
                subprocess.run(['tar', 'xzf', tracked_files_archive, '-C', tracked_files_dir], check=True)
                print(f"Saved tracked files for instance {instance_id} to {tracked_files_dir}")

            print(f"Saved output for instance {instance_id} to {output_file}")
            print(f"Saved logs for instance {instance_id} to {log_file}")

def convert_outputs_to_jsonl(output_dir: str):
    """Convert json outputs to SWE-bench jsonl format and combine them"""
    all_data = []
    
    # Iterate through instance directories
    for instance_dir in os.listdir(output_dir):
        instance_path = os.path.join(output_dir, instance_dir)
        if not os.path.isdir(instance_path):
            continue
            
        json_file = os.path.join(instance_path, f'{instance_dir}.json')
        if os.path.exists(json_file):
            # Read input file
            with open(json_file) as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = [data]
                all_data.extend(data)
    
    # Create combined output file
    if all_data:
        combined_df = pd.DataFrame(all_data)
        combined_output = os.path.join(output_dir, f'__combined_agentpress_output_{len(all_data)}.jsonl')
        combined_df.to_json(combined_output, orient='records', lines=True)
        print(f'\nCreated combined output file: {combined_output}')

if __name__ == "__main__":
    import argparse
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
    parser.add_argument("--agent-dir", required=True,
                        help="Path to your agent directory")
    parser.add_argument("--output-dir", default="./outputs",
                        help="Directory to save outputs (default: ./outputs)")
    parser.add_argument("--track-files", nargs="+",
                        help="List of files and/or folders to track and copy to outputs directory")
    parser.add_argument("--streamlit", action="store_true",
                        help="Launch streamlit thread viewer after execution")
    parser.add_argument("--no-stream", action="store_true",
                        help="Disable real-time output streaming")
    parser.add_argument("--interactive", action="store_true",
                        help="Enable interactive mode to send commands to Docker container")
    
    args = parser.parse_args()

    load_and_test_instances(
        num_examples=args.num_examples,
        test_index=args.test_index,
        start_index=args.range[0] if args.range else None,
        end_index=args.range[1] if args.range else None,
        dataset_name=args.dataset,
        split=args.split,
        agent_dir=args.agent_dir,
        output_dir=args.output_dir,
        track_files=args.track_files,
        no_stream=args.no_stream,
        interactive=args.interactive
    )
    
    # Convert json outputs to jsonl format and combine them
    convert_outputs_to_jsonl(args.output_dir)

    if args.streamlit:
        for idx, instance in enumerate(load_dataset(args.dataset, split=args.split).select(range(args.num_examples)), 1):
            instance_id = instance['instance_id']
            threads_dir = os.path.join(args.output_dir, f'{idx}_{instance_id}/files/tmp/agentpress/threads')
            if os.path.exists(threads_dir):
                print(f"\nLaunching streamlit thread viewer for instance {instance_id}...")
                subprocess.run([
                    'streamlit', 'run', 
                    'agent/agentpress/thread_viewer_ui.py', threads_dir
                ])
