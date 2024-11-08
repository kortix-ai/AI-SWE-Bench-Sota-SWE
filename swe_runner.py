import os
import sys
import json
import tempfile
import subprocess
from datasets import load_dataset
import argparse

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

    # Get Docker image for this instance
    docker_image = get_instance_docker_image(instance_id)
    print(f"Using Docker image: {docker_image}")

    # Pull the Docker image
    print("\nPulling Docker image...")
    subprocess.run(['docker', 'pull', docker_image], check=True)

    # Build the Docker run command
    container_name = f'swe_runner_{instance_id}'
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-index", type=int, default=1,
                        help="Run a specific test by index (starting from 1)")
    parser.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite",
                        help="Dataset to use (default: princeton-nlp/SWE-bench_Lite)")
    parser.add_argument("--split", default="test",
                        help="Dataset split to use (default: test)")
    parser.add_argument("--track-files", nargs="+",
                        help="List of files and/or folders to track")
    args = parser.parse_args()

    # Load dataset
    print(f"Loading dataset {args.dataset} ({args.split})...")
    dataset = load_dataset(args.dataset, split=args.split)

    instance = dataset[args.test_index - 1]  # Convert to 0-based index
    instance_id = instance['instance_id']
    problem_statement = instance['problem_statement']

    container_name = start_docker_container(instance, args.track_files or [])
    print(container_name)

    try:
        # Prepare problem.json
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            problem_file = f.name
            json.dump([instance], f)

        # Run agent.py
        cmd = [
            'python', 'agent/agent.py',
            '--problem-file', problem_file,
            '--container-name', container_name
        ]
        print("Running agent...")
        subprocess.run(cmd, check=True)

        # Run git commands inside the container
        git_commands = f"""
git config --global user.email "agent@example.com" && 
git config --global user.name "Agent" && 
git add -A && 
git commit -m "Agent modifications" || true && 
pwd && 
git diff --no-color {instance["base_commit"]} HEAD > /workspace/data/git_patch.diff && 
if [ ! -z "$TRACK_FILES" ]; then tar czf /workspace/data/tracked_files.tar.gz -C / $(echo "$TRACK_FILES" | sed "s|^/||") 2>/dev/null || true; fi
"""
        result = execute_command_in_container(container_name, git_commands)
        print(result.stdout)
        print(result.stderr)

        # Copy the git_patch.diff and tracked_files.tar.gz from the container
        os.makedirs('outputs', exist_ok=True)
        subprocess.run(['docker', 'cp', f'{container_name}:/workspace/data/git_patch.diff', f'outputs/{instance_id}.diff'], check=True)
        subprocess.run(['docker', 'cp', f'{container_name}:/workspace/data/tracked_files.tar.gz', f'outputs/{instance_id}_files.tar.gz'], check=True)

    finally:
        # Clean up
        stop_docker_container(container_name)

if __name__ == "__main__":
    main()
