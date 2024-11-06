import os
import json
import tempfile
import subprocess
from datasets import load_dataset
from typing import Any

def get_instance_docker_image(instance_id: str) -> str:
    """Get the docker image name for a specific instance."""
    DOCKER_IMAGE_PREFIX = os.environ.get('EVAL_DOCKER_IMAGE_PREFIX', 'docker.io/xingyaoww/')
    image_name = 'sweb.eval.x86_64.' + instance_id
    image_name = image_name.replace('__', '_s_')  # To comply with Docker naming conventions
    return (DOCKER_IMAGE_PREFIX.rstrip('/') + '/' + image_name).lower()

def get_swebench_workspace_dir_name(instance: dict) -> str:
    """Get the properly formatted workspace directory name."""
    return f"{instance['repo']}__{instance['version']}".replace('/', '__')

def load_and_test_instances(num_examples: int = 1, dataset_name: str = "princeton-nlp/SWE-bench_Lite", split: str = "test", agent_dir: str = "./agent", output_dir: str = "./outputs", track_files: list = None):
    """
    Load and test the first N instances from the dataset using Docker.

    Args:
        num_examples: Number of examples to test (default: 1)
        dataset_name: Name of the dataset to load from
        split: Dataset split to use
        agent_dir: Path to your agent directory
        output_dir: Directory to save outputs
    """
    # Load dataset
    print(f"Loading dataset {dataset_name} ({split})...")
    dataset = load_dataset(dataset_name, split=split)

    # Get the first N instances
    instances = dataset.select(range(min(num_examples, len(dataset))))

    os.makedirs(output_dir, exist_ok=True)

    print(f"\nWill test {len(instances)} instances:")
    for idx, instance in enumerate(instances, 1):
        instance_id = instance['instance_id']
        workspace_dir = get_swebench_workspace_dir_name(instance)

        # Clean up existing output files for this instance
        output_file = os.path.join(output_dir, f'{instance_id}.json')
        log_file = os.path.join(output_dir, f'{instance_id}__log.txt')
        tracked_files_dir = os.path.join(output_dir, f'{instance_id}_files')
        
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
                'docker', 'run', '--rm',
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
                    'pip install -r /agent/requirements.txt && '
                    'python /agent/agent.py '
                    f'--repo-path . '
                    f'--problem-file /workspace/data/problem.json && '
                    'git config --global user.email "agent@example.com" && '
                    'git config --global user.name "Agent" && '
                    'git add -A && '
                    'git commit -m "Agent modifications" || true && '
                    "echo 'LS' && ls -la && "
                    "pwd && "
                    f'git diff --no-color {instance["base_commit"]} HEAD > /workspace/data/git_patch.diff && '
                    f'if [ ! -z "$TRACK_FILES" ]; then tar czf /workspace/data/tracked_files.tar.gz -C / $(echo "$TRACK_FILES" | sed "s|^/||") 2>/dev/null || true; fi'
                )
            ]

            print("\nRunning test in Docker container...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error running agent for instance {instance_id}:\n{result.stderr}")
                continue
            else:
                print(f"Agent output for instance {instance_id}:\n{result.stdout}")

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
                tracked_files_dir = os.path.join(output_dir, f'{instance_id}_files')
                os.makedirs(tracked_files_dir, exist_ok=True)
                subprocess.run(['tar', 'xzf', tracked_files_archive, '-C', tracked_files_dir], check=True)
                print(f"Saved tracked files for instance {instance_id} to {tracked_files_dir}")

            print(f"Saved output for instance {instance_id} to {output_file}")
            print(f"Saved logs for instance {instance_id} to {log_file}")
            


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-examples", type=int, default=1,
                        help="Number of examples to test (default: 1)")
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

    args = parser.parse_args()

    load_and_test_instances(
        num_examples=args.num_examples,
        dataset_name=args.dataset,
        split=args.split,
        agent_dir=args.agent_dir,
        output_dir=args.output_dir,
        track_files=args.track_files
    )
    
    # Launch streamlit viewer if requested
    if args.streamlit:
        for instance in load_dataset(args.dataset, split=args.split).select(range(args.num_examples)):
            instance_id = instance['instance_id']
            threads_dir = os.path.join(args.output_dir, f'{instance_id}_files/tmp/agentpress/threads')
            if os.path.exists(threads_dir):
                print(f"\nLaunching streamlit thread viewer for instance {instance_id}...")
                subprocess.run([
                    'streamlit', 'run', 
                    'agent/agentpress/thread_viewer_ui.py', threads_dir
                ])
