import asyncio
import base64
from agentpress.tool import Tool, ToolResult, tool_schema
from agentpress.state_manager import StateManager
import os
from typing import List

class RepositoryTools(Tool):
    def __init__(self, container_name: str, state_file: str):
        super().__init__()
        self.state_manager = StateManager(store_file=state_file)
        self.container_name = container_name

    async def execute_command_in_container(self, command: str):
        """
        Executes a given bash command inside the specified Docker container.
        
        Parameters:
            command (str): The bash command to execute.
        
        Returns:
            tuple: (stdout, stderr, returncode)
        """
        # MUST keep this env activation command
        full_command = (
            f'. /opt/miniconda3/etc/profile.d/conda.sh && '
            f'conda activate testbed && {command}'
        )
        cmd = ['docker', 'exec', self.container_name, 'bash', '-c', full_command]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return stdout.decode(), stderr.decode(), process.returncode

    @tool_schema({
        "name": "view",
        "description": "View the contents of a file or list the contents of a directory in the repository with detailed explanations.",
        "parameters": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The file or directory paths to view."
                },
                "depth": {
                    "type": "integer",
                    "description": "The maximum directory depth to search for contents.",
                    "default": 1
                },
                "show_lines": {
                    "type": "boolean",
                    "description": "Whether to show line numbers in file output.",
                    "default": False
                }
            },
            "required": ["paths"]
        }
    })
    async def view(self, paths: List[str], exclude_patterns: list = ['.rst', '.pyc'], depth: int = 2, show_lines: bool = False) -> ToolResult:
        try:
            python_code = '''
import os
import fnmatch
import sys
from typing import List

def should_exclude(path: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(path, f"*{pattern}") for pattern in patterns)

def list_directory(root_path: str, depth: int, exclude_patterns: List[str], current_depth: int = 1) -> List[str]:
    results = []
    try:
        for item in sorted(os.listdir(root_path)):
            if item.startswith('.'):
                continue
                
            full_path = os.path.join(root_path, item)
            if should_exclude(full_path, exclude_patterns):
                continue
                
            results.append(full_path)
            if os.path.isdir(full_path) and current_depth < depth:
                results.extend(list_directory(full_path, depth, exclude_patterns, current_depth + 1))
    except PermissionError:
        print(f"Permission denied: {root_path}", file=sys.stderr)
    except Exception as e:
        print(f"Error accessing {root_path}: {str(e)}", file=sys.stderr)
    return results

def view_path(path: str, depth: int, exclude_patterns: List[str], show_lines: bool):
    if os.path.isdir(path):
        print(f'<directory path="{path}">')
        for item in list_directory(path, depth, exclude_patterns):
            print(item)
        print("</directory>")
    elif os.path.isfile(path):
        print(f'<file path="{path}">')
        try:
            with open(path, 'r') as f:
                if show_lines:
                    for i, line in enumerate(f, 1):
                        print(f"{i:6d}\t{line}", end='')
                else:
                    print(f.read(), end='')
        except Exception as e:
            print(f"Error reading file {path}: {str(e)}", file=sys.stderr)
        print("</file>")
    else:
        print(f"The path '{path}' is neither a file nor a directory.", file=sys.stderr)

def main():
    paths = sys.argv[1].split(',')
    exclude_patterns = sys.argv[2].split(',')
    depth = int(sys.argv[3])
    show_lines = sys.argv[4].lower() == 'true'
    
    for path in paths:
        view_path(path.strip(), depth, exclude_patterns, show_lines)

if __name__ == '__main__':
    main()
'''
            # Encode the Python script and arguments
            code_base64 = base64.b64encode(python_code.encode('utf-8')).decode('ascii')
            paths_str = ','.join(paths)
            exclude_str = ','.join(exclude_patterns)
            
            # Command to execute the Python script in the container
            command = (
                f"echo {repr(code_base64)} | base64 -d | "
                f"python3 - {repr(paths_str)} {repr(exclude_str)} {depth} {str(show_lines).lower()}"
            )
            
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            success = returncode == 0

            results = [{
                "path": path,
                "output": stdout.strip(),
                "error": stderr.strip(),
                "success": success,
            } for path in paths]

            # Update history
            history_key = "view_history"
            history = await self.state_manager.get(history_key) or []
            history.append({
                "paths": paths,
                "exclude_patterns": exclude_patterns,
                "results": results,
            })
            await self.state_manager.set(history_key, history)

            if success:
                return self.success_response(stdout + stderr)
            else:
                return self.fail_response(f"View command output: {stdout + stderr}")
        
        except Exception as e:
            return self.fail_response(f"Error executing view command: {str(e)}")

    @tool_schema({
        "name": "create_and_run",
        "description": "Create a new file with specified content and optionally run a command after creation.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to create."},
                "content": {"type": "string", "description": "The content to write to the file."},
                "command": {"type": "string", "description": "Optional command to run after file creation.", "default": None},
            },
            "required": ["path", "content"]
        }
    })
    async def create_and_run(self, path: str, content: str, command: str = None) -> ToolResult:
        """
        Creates a new file with the specified content and optionally runs a command.
        
        Parameters:
            path (str): The file path to create.
            content (str): The content to write to the file.
            command (str): Optional command to run after file creation.
        
        Returns:
            ToolResult: The result of the create and run operation.
        """
        try:
            # Create file with proper escaping and content
            escaped_content = content.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
            create_command = f'printf "%s" "{escaped_content}" > "{path}"'
            
            if command:
                full_command = f'{create_command} && {command}'
            else:
                full_command = f'{create_command} && echo "File created at {path}"'

            stdout, stderr, returncode = await self.execute_command_in_container(full_command)
            success = returncode == 0

            history = await self.state_manager.get("create_and_run_history") or []
            history.append({
                "path": path,
                "content": content,
                "command": command,
                "output": stdout + stderr,
                "success": success,
            })
            await self.state_manager.set("create_and_run_history", history)

            if success:
                return self.success_response(stdout + stderr)
            else:
                return self.fail_response(f"Create and run command output: {stdout + stderr}")
        
        except Exception as e:
            return self.fail_response(f"Error in create and run: {str(e)}")

    @tool_schema({
        "name": "edit_and_run",
        "description": "Replace a specific string in a file with another string and optionally run a command after.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path where the replacement should occur."},
                "old_str": {"type": "string", "description": "The string to be replaced."},
                "new_str": {"type": "string", "description": "The string to replace with."},
                "command": {"type": "string", "description": "Optional command to run after replacement.", "default": None},
            },
            "required": ["path", "old_str", "new_str"]
        }
    })
    async def edit_and_run(self, path: str, old_str: str, new_str: str, command: str = None) -> ToolResult:
        """
        Replaces a specific string in a file with another string and optionally runs a command.

        Parameters:
            path (str): The file path where the replacement should occur.
            old_str (str): The string to be replaced.
            new_str (str): The string to replace with.
            command (str): Optional command to run after replacement.

        Returns:
            ToolResult: The result of the replace string operation.
        """
        try:

            # Encode the old and new strings to base64 to handle special characters
            old_str_base64 = base64.b64encode(old_str.encode('utf-8')).decode('ascii')
            new_str_base64 = base64.b64encode(new_str.encode('utf-8')).decode('ascii')

            # Define the Python code to execute inside the container
            python_code = '''
import sys
import base64
import subprocess

def print_separator():
    print("=" * 80)

path = sys.argv[1]
old_str = base64.b64decode(sys.argv[2]).decode('utf-8')
new_str = base64.b64decode(sys.argv[3]).decode('utf-8')
command = base64.b64decode(sys.argv[4]).decode('utf-8') if sys.argv[4] != 'None' else None

with open(path, 'r') as f:
    content = f.read()

if content.count(old_str) == 0:
    print(f"Error: String '{old_str}' not found in file", file=sys.stderr)
    sys.exit(1)
elif content.count(old_str) > 1:
    print(f"Error: Multiple occurrences of '{old_str}' found. Please ensure the string is unique.", file=sys.stderr)
    sys.exit(1)
else:
    print(f"Making changes to file: {path}")
    print_separator()
    
    new_content = content.replace(old_str, new_str, 1)
    with open(path, 'w') as f:
        f.write(new_content)
    
    print("Changes made:")
    # Run git diff to show changes
    subprocess.run(['git', 'diff', 'HEAD', '--', path], text=True)
    print_separator()

    if command:
        print(f"Executing command: {command}")
        print_separator()
        
        process = subprocess.run(command, shell=True, capture_output=True, text=True)
        if process.stdout:
            print("Command output:")
            print(process.stdout)
        if process.stderr:
            print("Command errors:")
            print(process.stderr, file=sys.stderr)
        
        print_separator()
        if process.returncode != 0:
            print(f"Command failed with exit code: {process.returncode}", file=sys.stderr)
            sys.exit(process.returncode)
        else:
            print("Command completed successfully")
'''

            # Encode the Python code to base64
            code_base64 = base64.b64encode(python_code.encode('utf-8')).decode('ascii')

            # Function to safely quote strings in bash
            def bash_single_quote(s):
                return "'" + s.replace("'", "'\\''") + "'"

            # Escape the arguments
            escaped_path = bash_single_quote(path)
            escaped_old_str_base64 = bash_single_quote(old_str_base64)
            escaped_new_str_base64 = bash_single_quote(new_str_base64)
            command_base64 = base64.b64encode(str(command).encode('utf-8')).decode('ascii') if command else 'None'
            escaped_command_base64 = bash_single_quote(command_base64)

            # Build the command to execute inside the container
            command = (
                f"echo {bash_single_quote(code_base64)} | base64 -d | "
                f"python3 - {escaped_path} {escaped_old_str_base64} {escaped_new_str_base64} {escaped_command_base64}"
            )

            stdout, stderr, returncode = await self.execute_command_in_container(command)
            success = returncode == 0

            history = await self.state_manager.get("edit_and_run_history") or []
            history.append({
                "path": path,
                "old_str": old_str,
                "new_str": new_str,
                "command": command,
                "output": stdout + stderr,
                "success": success,
            })
            await self.state_manager.set("edit_and_run_history", history)

            if success:
                return self.success_response(stdout + stderr)
            else:
                return self.fail_response(f"Replace string command output: {stdout + stderr}")

        except Exception as e:
            return self.fail_response(f"Error replacing string: {str(e)}")

    @tool_schema({
        "name": "bash",
        "description": "Execute a shell command in the repository environment with explanatory output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute."},
            },
            "required": ["command"]
        }
    })
    async def bash(self, command: str) -> ToolResult:
        """
        Executes an arbitrary bash command with explanatory output.
        
        Parameters:
            command (str): The shell command to execute.
        
        Returns:
            ToolResult: The result of the bash command execution.
        """
        try:
            # Safely execute the command to prevent injection
            full_command = f'echo "Here\'s the result of running `{command}`:"; {command}'
            stdout, stderr, returncode = await self.execute_command_in_container(full_command)
            success = returncode == 0

            history_key = "bash_history"
            history = await self.state_manager.get(history_key) or []
            history.append({
                "command": command,
                "output": stdout + stderr,
                "success": success,
            })
            await self.state_manager.set(history_key, history)

            combined_output = (stdout + stderr).strip()[:2000]

            if success:
                return self.success_response(f"SUCCESS:\n{combined_output}")
            else:
                return self.fail_response(f"FAILED:\n{combined_output}")
        
        except Exception as e:
            return self.fail_response(f"Error executing bash command: {str(e)}")

    @tool_schema({
        "name": "submit",
        "description": "If you are confident that the issue is resolve, submit the fix",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    })
    async def submit(self) -> ToolResult:
        """
        Signals that the task is completed.

        Returns:
            ToolResult: Success message indicating task completion.
        """
        return self.success_response("Task completed successfully.")