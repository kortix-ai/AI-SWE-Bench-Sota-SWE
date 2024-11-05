import os
import json
import tempfile
import subprocess
from datasets import load_dataset
from typing import Any

# Configure docker image prefix
DOCKER_IMAGE_PREFIX = os.environ.get('EVAL_DOCKER_IMAGE_PREFIX', 'docker.io/xingyaoww/')

def get_instance_docker_image(instance_id: str) -> str:
    """Get the docker image name for a specific instance."""
    image_name = 'sweb.eval.x86_64.' + instance_id
    image_name = image_name.replace('__', '_s_')  # To comply with Docker naming conventions
    return (DOCKER_IMAGE_PREFIX.rstrip('/') + '/' + image_name).lower()

def get_swebench_workspace_dir_name(instance: dict) -> str:
    """Get the properly formatted workspace directory name."""
    return f"{instance['repo']}__{instance['version']}".replace('/', '__')

def load_and_test_instances(num_examples: int = 1, dataset_name: str = "princeton-nlp/SWE-bench_Lite", split: str = "test", agent_dir: str = "./agent", output_dir: str = "./outputs"):
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
            instance_file = os.path.join(temp_dir, 'swe-bench-instance.json')
            with open(instance_file, 'w') as f:
                json.dump([instance], f)

            # Build the Docker run command
            cmd = [
                'docker', 'run', '--rm',
                '-v', f'{temp_dir}:/swe_util/eval_data/instances',  # Mount instance data
                '-v', f'{os.path.abspath(agent_dir)}:/agent',        # Mount agent code
                '-e', f'SWE_INSTANCE_ID={instance_id}',
                '-e', 'PIP_CACHE_DIR=/root/.cache/pip',
                '-e', f'OPENAI_API_KEY={os.environ.get("OPENAI_API_KEY", "")}',
                '-e', f'ANTHROPIC_API_KEY={os.environ.get("ANTHROPIC_API_KEY", "")}',
                docker_image,
                '/bin/bash', '-c',
                # Prepare the environment and run the agent
                # 'source /swe_util/instance_swe_entry.sh && '
                'pip install --no-cache-dir -r /agent/requirements.txt && ',
                # 'python /agent/agent.py .'
            ]

            print("\nRunning test in Docker container...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error running agent for instance {instance_id}:\n{result.stderr}")
            else:
                print(f"Agent output for instance {instance_id}:\n{result.stdout}")
                # Save the agent's output
                output_file = os.path.join(output_dir, f'{instance_id}.json')
                with open(output_file, 'w') as f:
                    f.write(result.stdout)

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

    args = parser.parse_args()

    load_and_test_instances(
        num_examples=args.num_examples,
        dataset_name=args.dataset,
        split=args.split,
        agent_dir=args.agent_dir,
        output_dir=args.output_dir
    )
