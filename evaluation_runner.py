import argparse
import subprocess
import os
import sys
import json
import tempfile
import pandas as pd
from datasets import load_dataset
from swebench.harness.utils import load_swebench_dataset
from swebench.harness.test_spec import make_test_spec
from swebench.harness.grading import get_eval_report  

def get_instance_docker_image(instance_id: str) -> str:
    """Get the docker image name for a specific instance."""
    DOCKER_IMAGE_PREFIX = os.environ.get('EVAL_DOCKER_IMAGE_PREFIX', 'docker.io/xingyaoww/')
    image_name = 'sweb.eval.x86_64.' + instance_id
    image_name = image_name.replace('__', '_s_')  # To comply with Docker naming conventions
    return (DOCKER_IMAGE_PREFIX.rstrip('/') + '/' + image_name).lower()

def execute_command_in_container(container_name, command, timeout=None):
    """
    Execute a command inside the running Docker container and return the output.
    Maintains proper environment setup from old system.
    """
    full_command = f'. /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && {command}'
    cmd = ['docker', 'exec', container_name, 'bash', '-c', full_command]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result
    except subprocess.TimeoutExpired as e:
        print(f"Command timed out after {timeout} seconds: {command}")
        raise e

def prepare_dataset(dataset: pd.DataFrame, output_file: str, eval_n_limit: int = None):
    id_column = 'instance_id'
    print(f'Writing evaluation output to {output_file}')
    finished_ids: set[str] = set()
    if os.path.exists(output_file):
        with open(output_file, 'r') as f:
            for line in f:
                data = json.loads(line)
                finished_ids.add(str(data[id_column]))
        print(f'Output file {output_file} already exists. Loaded {len(finished_ids)} finished instances.')

    new_dataset = [
        instance
        for _, instance in dataset.iterrows()
        if str(instance[id_column]) not in finished_ids
    ]
    print(f'Finished instances: {len(finished_ids)}, Remaining instances: {len(new_dataset)}')

    if eval_n_limit and eval_n_limit > 0:
        new_dataset = new_dataset[:eval_n_limit]
        print(f'Limiting evaluation to first {eval_n_limit} instances.')

    return pd.DataFrame(new_dataset)

def run_evaluation(
    dataset: pd.DataFrame,
    output_file: str,
    output_dir: str,
    num_workers: int,
    process_instance_func,
):
    from multiprocessing import Pool
    from tqdm import tqdm

    total_instances = len(dataset)
    pbar = tqdm(total=total_instances, desc='Instances processed')
    output_fp = open(output_file, 'a')

    def update_progress(result):
        pbar.update(1)
        pbar.set_description(f'Instance {result["instance_id"]}')
        pbar.set_postfix_str(f'Test Result: {str(result["test_result"]["report"])[:100]}...')
        output_fp.write(json.dumps(result) + '\n')
        output_fp.flush()

        # Save per-instance evaluation result
        instance_id = result['instance_id']
        instance_output_dir = os.path.join(output_dir, f"{instance_id}")
        os.makedirs(instance_output_dir, exist_ok=True)
        eval_result_path = os.path.join(instance_output_dir, f"{instance_id}_evaluation_result.json")
        with open(eval_result_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Saved evaluation result for instance {instance_id}")

    if num_workers > 1:
        with Pool(num_workers) as pool:
            results = pool.imap_unordered(process_instance_func, [row for _, row in dataset.iterrows()])
            for result in results:
                update_progress(result)
    else:
        for _, instance in dataset.iterrows():
            result = process_instance_func(instance)
            update_progress(result)

    output_fp.close()
    print('\nEvaluation finished.\n')

def process_git_patch(patch: str) -> str:
    """Clean and normalize patch content."""
    if not isinstance(patch, str) or not patch.strip():
        return ''
        
    patch = patch.replace('\r\n', '\n')
    
    # Find first diff line - handle cases where there might be unexpected content before patch
    lines = patch.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('diff --git'):
            patch = '\n'.join(lines[i:])
            break
            
    return patch.rstrip() + '\n'

def process_instance(instance, output_dir):
    instance_id = instance['instance_id']
    model_patch = process_git_patch(instance['model_patch'])
    test_spec = instance['test_spec']
    
    # Create instance-specific output directory and log file
    instance_output_dir = os.path.join(output_dir, f"{instance_id}")
    os.makedirs(instance_output_dir, exist_ok=True)
    log_file = os.path.join(instance_output_dir, f'{instance_id}_eval.log')
    
    print(f'Starting evaluation for instance {instance_id}')
    
    test_result = {
        'apply_patch_output': '',
        'test_output': '',
        'report': {},
    }

    if not model_patch.strip():
        test_result['report']['empty_generation'] = True
        return {'instance_id': instance_id, 'test_result': test_result}

    # Start Docker container
    container_name = f'eval_runner_{instance_id}'
    docker_image = get_instance_docker_image(instance_id)

    # Remove existing container if any
    subprocess.run(['docker', 'rm', '-f', container_name], stdout=subprocess.DEVNULL)

    # Pull and start container
    subprocess.run(['docker', 'pull', docker_image], check=True)
    cmd = [
        'docker', 'run',
        '--name', container_name,
        '-d',
        '-e', f'SWE_INSTANCE_ID={instance_id}',
        docker_image,
        '/bin/bash', '-c',
        'tail -f /dev/null'
    ]
    subprocess.run(cmd, check=True)

    try:
        # Configure git
        git_config_cmd = (
            'cd /testbed && '
            'git config --global user.email "agent@example.com" && '
            'git config --global user.name "Agent"'
        )
        execute_command_in_container(container_name, git_config_cmd, timeout=60)

        # Apply model patch
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            f.write(model_patch)
            patch_file = f.name

        subprocess.run(['docker', 'cp', patch_file, f'{container_name}:/tmp/patch.diff'], check=True)

        # Apply patch with robust approach
        apply_patch_cmd = (
            'cd /testbed && '
            '(git apply -v /tmp/patch.diff && echo "APPLY_PATCH_PASS" || '
            '(echo "Failed to apply patch with git apply, trying with patch command..." && '
            '(patch --batch --fuzz=5 -p1 -i /tmp/patch.diff && echo "APPLY_PATCH_PASS" || '
            'echo "APPLY_PATCH_FAIL")))'
        )
        
        result = execute_command_in_container(container_name, apply_patch_cmd, timeout=600)
        apply_patch_output = result.stdout + result.stderr
        test_result['apply_patch_output'] = apply_patch_output

        # Log patch application results
        with open(log_file, 'w') as f:
            f.write(f"=== Evaluation for Instance {instance_id} ===\n\n")
            f.write("=== Patch Application Output ===\n")
            f.write(apply_patch_output + "\n\n")

        if 'APPLY_PATCH_FAIL' in apply_patch_output:
            print(f"Failed to apply patch for instance {instance_id}")
            test_result['report']['failed_apply_patch'] = True
            return {'instance_id': instance_id, 'test_result': test_result}

        elif 'APPLY_PATCH_PASS' in apply_patch_output:
            print(f"Patch applied successfully for instance {instance_id}")
            
            # Copy eval script to container
            with tempfile.NamedTemporaryFile('w', delete=False) as f:
                f.write(test_spec.eval_script)
                eval_script_file = f.name

            subprocess.run(['docker', 'cp', eval_script_file, f'{container_name}:/tmp/eval.sh'], check=True)
            execute_command_in_container(container_name, 'chmod +x /tmp/eval.sh')

            # Run evaluation with timeout
            try:
                result = execute_command_in_container(
                    container_name,
                    'cd /testbed && timeout 1800 /tmp/eval.sh',
                    timeout=1800
                )
                test_output = result.stderr + result.stdout 
                test_result['test_output'] = test_output
                
                with open(log_file, 'a') as f:
                    f.write("=== Test Output ===\n")
                    f.write(test_output + "\n\n")

                # Generate report using get_eval_report
                with tempfile.TemporaryDirectory() as temp_dir:
                    # Create a directory structure that matches the expected format
                    log_dir = os.path.join(temp_dir, 'logs', instance_id.lower())
                    os.makedirs(log_dir, exist_ok=True)
                    test_output_path = os.path.join(log_dir, 'test_output.txt')
                    with open(test_output_path, 'w') as f:
                        f.write(test_output)

                    _report = get_eval_report(
                        test_spec=test_spec,
                        prediction={
                            'model_patch': model_patch,
                            'instance_id': instance_id,
                        },
                        log_path=test_output_path,
                        include_tests_status=True,
                    )
                    report = _report[instance_id]
                    test_result['report'] = report
                    print(f"Report for instance {instance_id}: {report}")

            except subprocess.TimeoutExpired:
                print(f"Evaluation timed out after 1800 seconds for instance {instance_id}")
                test_result['report']['test_timeout'] = True
                with open(log_file, 'a') as f:
                    f.write("=== Test Output ===\n")
                    f.write(f"Timeout after 1800 seconds\n\n")
            except Exception as e:
                print(f"Error during evaluation for instance {instance_id}: {e}")
                test_result['report']['error_eval'] = True
                with open(log_file, 'a') as f:
                    f.write("=== Error ===\n")
                    f.write(f"Error during evaluation: {str(e)}\n\n")

            # Save git diff for reference
            try:
                git_diff_cmd = f'cd /testbed && git diff --no-color {instance["base_commit"]} HEAD'
                result = execute_command_in_container(container_name, git_diff_cmd, timeout=60)
                with open(os.path.join(instance_output_dir, f'{instance_id}_eval.diff'), 'w') as f:
                    f.write(result.stdout)
            except Exception as e:
                print(f"Error generating git diff for instance {instance_id}: {e}")

        else:
            print(f"Unexpected output when applying patch for {instance_id}")
            test_result['report']['error_eval'] = True
            with open(log_file, 'a') as f:
                f.write("\n=== Unexpected Patch Application Output ===\n")
                f.write(apply_patch_output)

        return {'instance_id': instance_id, 'test_result': test_result}

    except Exception as e:
        print(f"Error evaluating instance {instance_id}: {e}")
        test_result['report']['error_eval'] = True
        with open(log_file, 'a') as f:
            f.write("\n=== Fatal Error ===\n")
            f.write(f"Error: {str(e)}\n")
        return {'instance_id': instance_id, 'test_result': test_result}
    finally:
        # Cleanup
        subprocess.run(['docker', 'stop', container_name], stdout=subprocess.DEVNULL)
        subprocess.run(['docker', 'rm', container_name], stdout=subprocess.DEVNULL)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--input-file',
        type=str,
        required=True,
        help='Path to input predictions file',
    )
    parser.add_argument(
        '--output-dir',
        default='./outputs',
        help='Directory to save evaluation outputs',
    )
    parser.add_argument(
        '--dataset',
        type=str,
        default='princeton-nlp/SWE-bench_Lite',
        help='Dataset name to use',
    )
    parser.add_argument(
        '--split',
        default='test',
        help='Dataset split to use',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=1800,
        help='Timeout for evaluation in seconds',
    )
    parser.add_argument(
        '--num-workers',
        type=int,
        default=1,
        help='Number of parallel workers',
    )
    args = parser.parse_args()

    # Load predictions
    with open(args.input_file, 'r') as f:
        predictions = [json.loads(line) for line in f]

    # Convert predictions to DataFrame
    df_predictions = pd.DataFrame(predictions)

    # Ensure required columns are present
    required_columns = {'instance_id', 'model_patch'}
    if not required_columns.issubset(df_predictions.columns):
        raise ValueError(f"Input file must contain the following columns: {required_columns}")

    # Load dataset
    print(f"Loading dataset {args.dataset} ({args.split})...")
    dataset = load_swebench_dataset(args.dataset, args.split)
    instance_id_to_instance = {instance['instance_id']: instance for instance in dataset}
    print(f"Loaded {len(dataset)} instances from the dataset.")

    # Merge predictions with dataset
    df_predictions['instance'] = df_predictions['instance_id'].apply(lambda x: instance_id_to_instance.get(x))
    df_predictions['test_spec'] = df_predictions['instance'].apply(make_test_spec)

    # Filter out any instances not found in the dataset
    df_predictions = df_predictions[df_predictions['instance'].notnull()]
    print(f"Evaluating {len(df_predictions)} instances.")

    # Prepare dataset for evaluation
    output_file = os.path.join(args.output_dir, 'evaluation_results.jsonl')
    os.makedirs(args.output_dir, exist_ok=True)

    # Prepare dataset
    instances = prepare_dataset(df_predictions, output_file)

    def process_instance_wrapper(instance):
        return process_instance(instance, args.output_dir)

    # Run evaluation
    run_evaluation(
        dataset=instances,
        output_file=output_file,
        output_dir=args.output_dir,
        num_workers=args.num_workers,
        process_instance_func=process_instance_wrapper,
    )

    print("\nEvaluation completed.")

if __name__ == '__main__':
    main()