import os
import tiktoken

def count_tokens(line):
    # Use cl100k_base encoding (same as used by GPT-4)
    encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(line))

def process_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            for line in file:
                # Remove trailing newline
                line = line.rstrip('\n')
                # Get first 30 characters
                preview = line[:30].ljust(30)
                # Count tokens
                token_count = count_tokens(line)
                print(f"{preview} | Tokens: {token_count}")
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    # Look for .old.run.xml file in current directory
    target_file = ".old.run.xml"
    if os.path.exists(target_file):
        process_file(target_file)
    else:
        print(f"Error: '{target_file}' not found in current directory.")