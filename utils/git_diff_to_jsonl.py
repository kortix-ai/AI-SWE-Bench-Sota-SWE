import argparse
import json
import subprocess
import os

def main():
    # Setup argument parser
    parser = argparse.ArgumentParser(description='Generate JSONL from git diff')
    parser.add_argument('folder_path', type=str, help='Path to the folder to run git diff')
    parser.add_argument('--output', type=str, help='Output JSONL file path')
    parser.add_argument('--eval', action='store_true', default=True, help='Run evaluation after generating JSONL')
    
    args = parser.parse_args()
    
    # Convert folder path to absolute path
    abs_folder_path = os.path.abspath(args.folder_path)
    
    # Get folder name for instance_id and output file
    folder_name = os.path.basename(os.path.normpath(abs_folder_path))
    
    # Set output path to be at the same level as input folder
    if args.output is None:
        parent_dir = os.path.dirname(abs_folder_path)
        args.output = os.path.join(parent_dir, f"{folder_name}_output.jsonl")
    
    # Change to target directory
    os.chdir(abs_folder_path)
    
    try:
        # Run git diff command
        diff_output = subprocess.check_output(['git', 'diff', '--no-color', 'HEAD'], 
                                           stderr=subprocess.STDOUT,
                                           universal_newlines=True)
        
        # Create JSON object
        diff_data = {
            "instance_id": folder_name,
            "model_patch": diff_output,
            "model_name_or_path": "DefaultModel"
        }
        
        # Create parent directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        
        # Write to JSONL file
        with open(args.output, 'w') as f:
            f.write(json.dumps(diff_data) + '\n')
            
        print(f"Diff output saved to {args.output}")

        # Run evaluation if enabled
        if args.eval:
            try:
                parent_dir = os.path.dirname(os.path.abspath(args.output))
                script_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                eval_script_path = os.path.join(script_parent_dir, 'evaluation.py')
                
                eval_cmd = [
                    'python', eval_script_path,
                    '--dataset', 'princeton-nlp/SWE-bench_Verified',
                    '--input-file', args.output,
                    '--output-dir', parent_dir
                ]
                subprocess.run(eval_cmd, check=True)
                print("Evaluation completed successfully")
            except subprocess.CalledProcessError as e:
                print(f"Error running evaluation: {e}")
        
    except subprocess.CalledProcessError as e:
        print(f"Error running git diff: {e}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()