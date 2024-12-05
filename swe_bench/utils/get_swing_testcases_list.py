import json
import argparse

# example run :  
"""python utils/get_swing_testcases_list.py  /home/nightfury/projects/AI-SWE-Bench-Sota-SWE/experiments/evaluation/verified/20241029_OpenHands-CodeAct-2.1-sonnet-20241022/results/results.json  /home/nightfury/projects/AI-SWE-Bench-Sota-SWE/experiments/evaluation/verified/20241022_tools_claude-3-5-sonnet-updated/results/results.json --output diff_claude_openhands.json --name1 openhands --name2 claude
"""

TOTAL_PROBLEMS = {
    'lite': 300,
    'verified': 500,
    'full': 2000
}

def main():
    parser = argparse.ArgumentParser(description='Compare resolved tasks in two JSON files and output the difference.')
    parser.add_argument('json_file1', type=str, help='Path to the first JSON file')
    parser.add_argument('json_file2', type=str, help='Path to the second JSON file')
    parser.add_argument('--output', type=str, required=True, help='Path to the output JSON file')
    parser.add_argument('--name1', type=str, required=True, help='Name for the first file source')
    parser.add_argument('--name2', type=str, required=True, help='Name for the second file source')
    parser.add_argument('--type', type=str, choices=['lite', 'verified', 'full'], 
                       default='verified', help='Type of evaluation dataset')
    args = parser.parse_args()

    with open(args.json_file1, 'r') as f:
        data1 = json.load(f)

    with open(args.json_file2, 'r') as f:
        data2 = json.load(f)

    resolved1 = set(data1.get('resolved', []))
    resolved2 = set(data2.get('resolved', []))

    unique_to_first = sorted(resolved1 - resolved2)
    unique_to_second = sorted(resolved2 - resolved1)

    # Get total unique problems attempted by either model
    total_problems = TOTAL_PROBLEMS[args.type]
    all_problems = resolved1.union(resolved2)

    # Add statistics
    stats = {
        'total_resolved_in_first': len(resolved1),
        'total_resolved_in_second': len(resolved2),
        'unique_to_first': len(unique_to_first),
        'unique_to_second': len(unique_to_second),
        'common_resolved': len(resolved1.intersection(resolved2)),
        'total_problems': total_problems,
        'percent_solved_first': round(len(resolved1) / total_problems * 100, 2),
        'percent_solved_second': round(len(resolved2) / total_problems * 100, 2),
        'percent_solved_combined': round(len(all_problems) / total_problems * 100, 2)
    }

    output_data = {
        f'resolved_unique_to_{args.name1}': unique_to_first,
        f'resolved_unique_to_{args.name2}': unique_to_second,
    }

    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)

    # Print statistics
    print(f"\nStatistics for {args.type} dataset ({total_problems} problems):")
    print(f"Total unique problems: {total_problems}")
    print(f"Total resolved in {args.name1}: {stats['total_resolved_in_first']} ({stats['percent_solved_first']}%)")
    print(f"Total resolved in {args.name2}: {stats['total_resolved_in_second']} ({stats['percent_solved_second']}%)")
    print(f"Success unique to {args.name1}: {stats['unique_to_first']}")
    print(f"Success unique to {args.name2}: {stats['unique_to_second']}")
    print(f"Common resolved tasks: {stats['common_resolved']}")
    print(f"If we solve all, -> solve rate can be achieved: {stats['percent_solved_combined']}%")

if __name__ == '__main__':
    main()