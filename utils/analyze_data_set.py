import argparse
import json
from datasets import load_dataset
from typing import List, Dict, Set
import os

def load_results(results_path: str) -> Set[str]:
    """Load results file and return set of resolved instances"""
    if not os.path.exists(results_path):
        return set()
    with open(results_path) as f:
        results = json.load(f)
    return set(results.get('resolved', []))

def download_and_prepare_dataset(
    dataset_name: str = "princeton-nlp/SWE-bench_Lite",
    split: str = "test",
    resolved_instances: Set[str] = set()
) -> Dict:
    """
    Downloads and prepares the dataset.
    Returns dict with instances and their status.
    """
    print(f"Loading dataset {dataset_name} ({split})...")
    dataset = load_dataset(dataset_name, split=split)
    total_count = len(dataset)
    print(f"Loaded {total_count} instances")
    
    instances = []
    for item in dataset:
        instance_id = item['instance_id']
        is_success = instance_id in resolved_instances
        mark = "✓" if is_success else "✗"
        instances.append({
            "display": f"{mark} {instance_id}",
            "success": is_success
        })
    
    return {'instances': instances}, total_count

def save_instances(instances: List[Dict], output_path: str):
    """Save instances to JSON file"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(instances, f, indent=2)
    print(f"Saved {len(instances)} instances to {output_path}")

def save_instances_text(instances: Dict, output_path: str, total_count: int):
    """Save instances to text file with formatting"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    success_count = 0
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"Total number of test cases: {total_count}\n\n")
        for i, instance in enumerate(instances['instances'], 1):
            if instance['success']:
                success_count += 1
                f.write(f"{i}. {instance['display']}     --     {success_count}\n")
            else:
                f.write(f"{i}. {instance['display']}\n")
    print(f"Saved {len(instances['instances'])} instances to {output_path}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--dataset',
        type=str,
        default='princeton-nlp/SWE-bench_Lite',
        help='Dataset name to use'
    )
    parser.add_argument(
        '--split',
        type=str,
        default='test',
        help='Dataset split to use'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='outputs/instances.txt',  # Changed default to .txt
        help='Output text file path'
    )
    parser.add_argument(
        '--results',
        type=str,
        default='outputs/openhands_results.json',
        help='Results JSON file path containing resolved instances'
    )
    args = parser.parse_args()

    # Load resolved instances
    resolved_instances = load_results(args.results)
    
    # Download and prepare dataset
    instances, total_count = download_and_prepare_dataset(args.dataset, args.split, resolved_instances)
    
    # Save to text file
    save_instances_text(instances, args.output, total_count)

if __name__ == '__main__':
    main()