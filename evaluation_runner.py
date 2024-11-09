import argparse
import subprocess
import os
import sys
import json
import tempfile
import time

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
    container_name = f'eval_runner_{instance_id}'

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

def execute_command_in_container(container_name, command, timeout=None):
    """
    Execute a command inside the running Docker container and return the output.
    """
    full_command = f'. /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && {command}'
    cmd = ['docker', 'exec', container_name, 'bash', '-c', full_command]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-file', type=str, required=True, help='Path to the combined JSONL output file from swe_runner')
    parser.add_argument('--output-dir', default='./eval_outputs', help='Directory to save evaluation outputs')
    parser.add_argument('--timeout', type=int, default=1800, help='Timeout for evaluation in seconds')
    args = parser.parse_args()

    # Load instances
    with open(args.input_file, 'r') as f:
        instances = [json.loads(line) for line in f]

    os.makedirs(args.output_dir, exist_ok=True)

    # Process each instance
    for idx, instance in enumerate(instances):
        instance_id = instance['instance_id']
        model_patch = instance['model_patch']
        eval_script = instance.get('eval_script', None)

        # Create instance-specific output directory
        instance_output_dir = os.path.join(args.output_dir, f"{idx}_{instance_id}")
        os.makedirs(instance_output_dir, exist_ok=True)

        # Start docker container
        container_name = start_docker_container(instance, track_files=[])

        try:
            # Copy model_patch into container
            with tempfile.NamedTemporaryFile('w', delete=False) as f:
                patch_file = f.name
                f.write(model_patch)
            # Copy patch file into container
            subprocess.run(['docker', 'cp', patch_file, f'{container_name}:/tmp/patch.diff'], check=True)

            # Apply the patch
            apply_patch_cmd = (
                'cd /workspace && '
                '(git apply -v /tmp/patch.diff && echo "APPLY_PATCH_PASS" || '
                '(echo "Failed to apply patch with git apply, trying with patch command..." && '
                '(patch -p1 -i /tmp/patch.diff && echo "APPLY_PATCH_PASS" || echo "APPLY_PATCH_FAIL")))'
            )
            result = execute_command_in_container(container_name, apply_patch_cmd)
            apply_patch_output = result.stdout + result.stderr
            # Save apply_patch_output
            with open(os.path.join(instance_output_dir, f'{instance_id}_apply_patch_output.txt'), 'w') as f:
                f.write(apply_patch_output)

            if 'APPLY_PATCH_FAIL' in apply_patch_output:
                print(f"Failed to apply patch for instance {instance_id}")
                # Save failure info
                evaluation_result = {
                    'instance_id': instance_id,
                    'apply_patch_success': False,
                    'apply_patch_output': apply_patch_output,
                }
                with open(os.path.join(instance_output_dir, f'{instance_id}_evaluation_result.json'), 'w') as f:
                    json.dump(evaluation_result, f, indent=2)
                continue
            else:
                print(f"Patch applied successfully for instance {instance_id}")

            # Copy eval_script into container
            if eval_script:
                with tempfile.NamedTemporaryFile('w', delete=False) as f:
                    eval_script_file = f.name
                    f.write(eval_script)
                # Copy eval script into container
                subprocess.run(['docker', 'cp', eval_script_file, f'{container_name}:/tmp/eval.sh'], check=True)
                # Make it executable
                execute_command_in_container(container_name, 'chmod +x /tmp/eval.sh')
                # Run eval script
                eval_cmd = '/tmp/eval.sh'
            else:
                # Default evaluation command
                eval_cmd = 'make test'  # Replace with your default command if needed

            # Run evaluation
            print(f"Running evaluation for instance {instance_id}...")
            start_time = time.time()
            try:
                eval_result = execute_command_in_container(container_name, eval_cmd, timeout=args.timeout)
                eval_output = eval_result.stdout + eval_result.stderr
                eval_success = eval_result.returncode == 0
                elapsed_time = time.time() - start_time
            except subprocess.TimeoutExpired:
                print(f"Evaluation timed out for instance {instance_id}")
                eval_output = ''
                eval_success = False
                elapsed_time = args.timeout

            # Save evaluation output
            eval_output_path = os.path.join(instance_output_dir, f'{instance_id}_eval_output.txt')
            print(f"Saving evaluation output to {eval_output_path}")
            with open(eval_output_path, 'w') as f:
                f.write(eval_output)

            # Save evaluation result
            evaluation_result = {
                'instance_id': instance_id,
                'apply_patch_success': True,
                'apply_patch_output': apply_patch_output,
                'evaluation_output': eval_output,
                'evaluation_success': eval_success,
                'evaluation_time': elapsed_time,
            }
            eval_result_path = os.path.join(instance_output_dir, f'{instance_id}_evaluation_result.json')
            print(f"Saving evaluation result to {eval_result_path}")
            with open(eval_result_path, 'w') as f:
                json.dump(evaluation_result, f, indent=2)
            print(f"Saved evaluation result for instance {instance_id}")

        except Exception as e:
            print(f"Error processing instance {instance_id}: {e}")
        finally:
            # Stop docker container
            stop_docker_container(container_name)

if __name__ == "__main__":
    main()
