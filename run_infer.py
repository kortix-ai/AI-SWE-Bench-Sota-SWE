import os
import json
import subprocess
import argparse
import tempfile
from datasets import load_dataset

def get_instance_docker_image(instance_id: str) -> str:
    """Get the docker image name for a specific instance."""
    DOCKER_IMAGE_PREFIX = os.environ.get('EVAL_DOCKER_IMAGE_PREFIX', 'ghcr.io/princeton-nlp/')
    image_name = 'sweb.eval.x86_64.' + instance_id
    image_name = image_name.replace('__', '_s_')  # To comply with Docker naming conventions
    return (DOCKER_IMAGE_PREFIX.rstrip('/') + '/' + image_name).lower()

def process_instance(instance: dict, agent_dir: str, output_dir: str):
    instance_id = instance['instance_id']
    print(f"Processing instance: {instance_id}")

    # Get the Docker image for this instance
    docker_image = get_instance_docker_image(instance_id)
    print(f"Using Docker image: {docker_image}")

    # Pull the Docker image
    print("Pulling Docker image...")
    subprocess.run(['docker', 'pull', docker_image], check=True)

    # Prepare temporary directory to store instance data
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save instance data
        instance_file = os.path.join(temp_dir, 'swe-bench-instance.json')
        with open(instance_file, 'w') as f:
            json.dump([instance], f)

        # Run agent inside Docker
        cmd = [
            'docker', 'run', '--rm',
            '-v', f'{os.path.abspath(agent_dir)}:/agent',  # Mount agent code
            '-v', f'{temp_dir}:/swe_util/eval_data/instances',  # Mount instance data
            '-e', f'SWE_INSTANCE_ID={instance_id}',
            '-e', f'OPENAI_API_KEY={os.environ.get("OPENAI_API_KEY", "")}',
            docker_image,
            '/bin/bash', '-c',
            'source /swe_util/instance_swe_entry.sh && cd /workspace && pip install -r /agent/requirements.txt && python /agent/agent.py'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error running agent for instance {instance_id}: {result.stderr}")
        else:
            print(f"Agent output for instance {instance_id}:\n{result.stdout}")
            # Save the agent's output
            output_file = os.path.join(output_dir, f'{instance_id}.json')
            with open(output_file, 'w') as f:
                f.write(result.stdout)

def main():
    parser = argparse.ArgumentParser(description="Run SWE-Bench tests with a custom agent.")
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

    os.makedirs(args.output_dir, exist_ok=True)

    # Load dataset
    dataset = load_dataset(args.dataset, split=args.split)

    # Get the first N instances
    instances = dataset.select(range(min(args.num_examples, len(dataset))))

    # Process each instance
    for instance in instances:
        process_instance(instance, args.agent_dir, args.output_dir)

if __name__ == "__main__":
    main()
