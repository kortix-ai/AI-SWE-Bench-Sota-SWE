import argparse
import subprocess
import sys
import os
from datasets import load_dataset

def clone_and_checkout(repo_url: str, name_instance: str, base_commit: str):
    repo_dir = os.path.join('repo', name_instance)
    subprocess.run(['git', 'clone', repo_url, repo_dir], check=True)
    subprocess.run(['git', 'checkout', base_commit], cwd=repo_dir, check=True)

def main():
    parser = argparse.ArgumentParser(description="Clone repositories and check out to specific commits based on dataset.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--range", nargs=2, type=int, metavar=('START', 'END'),
                       help="Clone repositories from START to END index")
    group.add_argument("--test-index", type=int,
                       help="Clone a specific test by index")
    group.add_argument("--instance-id", type=str,
                       help="Clone a specific instance by instance_id")
    parser.add_argument("--dataset", 
                        # default="princeton-nlp/SWE-bench_Lite",
                        default="princeton-nlp/SWE-bench_Verified",
                        help="Dataset to use")
    args = parser.parse_args()

    # Load dataset
    dataset = load_dataset(args.dataset, split='test')  # Adjust split if needed

    # Select instances based on arguments
    if args.instance_id is not None:
        instances = dataset.filter(lambda x: x['instance_id'] == args.instance_id)
    elif args.test_index is not None:
        instances = dataset.select([args.test_index - 1])  # 0-based index
    elif args.range is not None:
        start, end = args.range
        instances = dataset.select(range(start - 1, end))  # 0-based index
    else:
        instances = dataset  # Clone all if no specific selection

    for instance in instances:
        repo_url = "https://github.com/" + instance['repo']
        name_instance = instance['instance_id']
        base_commit = instance['base_commit']
        clone_and_checkout(repo_url, name_instance, base_commit)
        with open(os.path.join('repo', name_instance, 'pr_description.xml'), 'w') as f:
            f.write(f'<pr_description>\n{instance["problem_statement"]}\n</pr_description>')
        print("Base commit : ", base_commit)

if __name__ == "__main__":
    main()