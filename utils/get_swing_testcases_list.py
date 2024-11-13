import json
import argparse

def main():
    parser = argparse.ArgumentParser(description='Compare resolved tasks in two JSON files and output the difference.')
    parser.add_argument('json_file1', type=str, help='Path to the first JSON file')
    parser.add_argument('json_file2', type=str, help='Path to the second JSON file')
    parser.add_argument('--output', type=str, required=True, help='Path to the output JSON file')
    args = parser.parse_args()

    with open(args.json_file1, 'r') as f:
        data1 = json.load(f)

    with open(args.json_file2, 'r') as f:
        data2 = json.load(f)

    resolved1 = set(data1.get('resolved', []))
    resolved2 = set(data2.get('resolved', []))

    unique_tasks = sorted(resolved1 - resolved2)

    output_data = {'resolved_unique_to_first_file': unique_tasks}

    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)

if __name__ == '__main__':
    main()