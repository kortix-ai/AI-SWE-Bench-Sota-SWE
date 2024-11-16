import asyncio
import base64
from agentpress.tool import Tool, ToolResult, tool_schema
from agentpress.state_manager import StateManager
import os
from typing import List, Optional
from datetime import datetime

class BashSession:
    """Manages a persistent bash session in the Docker container."""
    
    def __init__(self, container_name: str):
        self.container_name = container_name
        self._process: Optional[asyncio.subprocess.Process] = None
        self._started = False
        
    async def start(self):
        """Start a new bash session in the container."""
        if self._started:
            return
            
        cmd = ['docker', 'exec', '-i', self.container_name, 'bash']
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        self._started = True
        
        # Initialize conda environment
        await self.execute('. /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed')
        
    async def execute(self, command: str) -> tuple[str, str, int]:
        """Execute a command in the bash session."""
        if not self._started or not self._process:
            await self.start()
            
        assert self._process and self._process.stdin and self._process.stdout and self._process.stderr
        
        # Add command terminator to help identify end of output
        terminator = f"__CMD_COMPLETE_{os.urandom(8).hex()}__"
        full_command = f"{command}\necho {terminator}\n"
        
        try:
            self._process.stdin.write(full_command.encode())
            await self._process.stdin.drain()
            
            # Read output until terminator
            output = []
            error = []
            while True:
                line = await self._process.stdout.readline()
                decoded = line.decode().rstrip()
                if decoded == terminator:
                    break
                output.append(decoded)
                
            # Check for any stderr output
            while self._process.stderr.at_eof():
                line = await self._process.stderr.readline()
                if line:
                    error.append(line.decode().rstrip())
                    
            return '\n'.join(output), '\n'.join(error), 0
            
        except Exception as e:
            return '', str(e), 1
            
    def stop(self):
        """Stop the bash session."""
        if self._started and self._process:
            self._process.terminate()
        self._started = False

class RepositoryTools(Tool):
    def __init__(self, container_name: str, state_file: str):
        super().__init__()
        self.state_manager = StateManager(store_file=state_file)
        self.container_name = container_name
        self._bash_session = BashSession(container_name)
        # Initialize workspace state
        asyncio.create_task(self._init_workspace_state())

    async def _init_workspace_state(self):
        """Initialize the workspace state with empty structures."""
        workspace_state = {
            "file_tree": {},           # Current directory structure
            "open_files": {},          # Currently open files and their contents
            "terminal_session": [],    # Current terminal session output (last N commands)
        }
        await self.state_manager.set("workspace", workspace_state)

    async def _parse_directory_listing(self, output: str) -> dict:
        """Parse directory listing output into a tree structure."""
        file_tree = {}
        
        for line in output.strip().split('\n'):
            if line.startswith('<directory') or line.startswith('</directory'):
                continue
                
            # Clean and normalize path
            path = line.strip()
            if path.startswith('/testbed/'):
                path = path[9:]  # Remove /testbed/ prefix
            if not path:
                continue
                
            # Build tree structure
            parts = path.split('/')
            current = file_tree
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    current[part] = "file"
                else:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
        
        return file_tree

    async def _update_file_tree(self, file_tree: dict):
        """Update the file tree in workspace state."""
        workspace = await self.state_manager.get("workspace")
        workspace["file_tree"] = file_tree
        await self.state_manager.set("workspace", workspace)

    async def _update_open_file(self, path: str, content: str):
        """Update or add a file in the open files list."""
        workspace = await self.state_manager.get("workspace")
        workspace["open_files"][path] = {
            "content": content,
            "last_modified": datetime.now().isoformat()
        }
        await self.state_manager.set("workspace", workspace)

    async def _update_terminal(self, command: str, output: str, success: bool):
        """Update terminal session with new output."""
        workspace = await self.state_manager.get("workspace")
        workspace["terminal_session"].append({
            "command": command,
            "output": output,
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
        # Keep only last 5 commands
        workspace["terminal_session"] = workspace["terminal_session"][-5:]
        await self.state_manager.set("workspace", workspace)

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

    async def _extract_file_content(self, output: str) -> str:
        """Extract file content from view output."""
        content_lines = []
        in_file_content = False
        
        for line in output.strip().split('\n'):
            if line.startswith('<file'):
                in_file_content = True
                continue
            elif line.startswith('</file'):
                in_file_content = False
                continue
            if in_file_content and '\t' in line:
                content_lines.append(line.split('\t', 1)[1])
        
        return '\n'.join(content_lines)

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
                    "default": 2
                },
            },
            "required": ["paths"]
        }
    })
    async def view(self, paths: List[str], exclude_patterns: list = ['.rst', '.pyc'], depth: int = 2) -> ToolResult:
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

def view_path(path: str, depth: int, exclude_patterns: List[str]):
    if os.path.isdir(path):
        print(f'<directory path="{path}">')
        for item in list_directory(path, depth, exclude_patterns):
            print(item)
        print("</directory>")
    elif os.path.isfile(path):
        print(f'<file path="{path}">')
        try:
            with open(path, 'r') as f:
                for i, line in enumerate(f, 1):
                    print(f"{i:6d}\t{line}", end='')
        except Exception as e:
            print(f"Error reading file {path}: {str(e)}", file=sys.stderr)
        print("</file>")
    else:
        print(f"The path '{path}' is neither a file nor a directory.", file=sys.stderr)

def main():
    paths = sys.argv[1].split(',')
    exclude_patterns = sys.argv[2].split(',')
    depth = int(sys.argv[3])
    
    for path in paths:
        view_path(path.strip(), depth, exclude_patterns)

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
                f"python3 - {repr(paths_str)} {repr(exclude_str)} {depth}"
            )
            
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            success = returncode == 0

            if success and not stderr.strip():
                for path in paths:
                    if os.path.isdir(path):
                        # Update file tree from directory listing
                        file_tree = await self._parse_directory_listing(stdout)
                        await self._update_file_tree(file_tree)
                    else:
                        # For files, extract content and add to open_files
                        content = await self._extract_file_content(stdout)
                        if content:
                            await self._update_open_file(path, content)
                
                return self.success_response(str(stdout.strip()))
            else:
                return self.fail_response(f"View command failed: {stderr.strip()}")
        
        except Exception as e:
            return self.fail_response(f"Error executing view command: {str(e)}")

    @tool_schema({
        "name": "create_file",
        "description": "Create a new file w ith specified content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to create."},
                "content": {"type": "string", "description": "The content to write to the file."},
            },
            "required": ["path", "content"]
        }
    })
    async def create_file(self, path: str, content: str) -> ToolResult:
        """Creates a new file with the specified content."""
        try:
            # Create directory if it doesn't exist
            directory = os.path.dirname(path)
            mkdir_command = f'mkdir -p "{directory}"'
            await self.execute_command_in_container(mkdir_command)

            # Create file with proper escaping and content
            escaped_content = content.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
            create_command = f'printf "%s" "{escaped_content}" > "{path}"'
            
            stdout, stderr, returncode = await self.execute_command_in_container(create_command)
            success = returncode == 0

            if success and not stderr.strip():
                # Update workspace state
                await self._update_file_tree(path)
                await self._update_open_file(path, content)
                
                return self.success_response(f"File created at {path}")
            else:
                error_msg = stderr.strip() if stderr.strip() else "Unknown error occurred"
                return self.fail_response(f"Create file failed: {error_msg}")
        
        except Exception as e:
            return self.fail_response(f"Error creating file: {str(e)}")

        except Exception as e:
            return self.fail_response(f"Error reading file: {str(e)}")

    @tool_schema({
        "name": "replace_string",
        "description": "Replace a specific string in a file with another string.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path where the replacement should occur."},
                "old_str": {"type": "string", "description": "The string to be replaced."},
                "new_str": {"type": "string", "description": "The string to replace with."},
            },
            "required": ["path", "old_str", "new_str"]
        }
    })
    async def replace_string(self, path: str, old_str: str, new_str: str) -> ToolResult:
        """
        Replaces a specific string in a file with another string.

        Parameters:
            path (str): The file path where the replacement should occur.
            old_str (str): The string to be replaced.
            new_str (str): The string to replace with.

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
import difflib

path = sys.argv[1]
old_str = base64.b64decode(sys.argv[2]).decode('utf-8')
new_str = base64.b64decode(sys.argv[3]).decode('utf-8')

with open(path, 'r') as f:
    content = f.read()

if content.count(old_str) == 0:
    print("String '{}' not found in file".format(old_str), file=sys.stderr)
    sys.exit(1)
elif content.count(old_str) > 1:
    print("Multiple occurrences of '{}' found. Please ensure the string is unique.".format(old_str), file=sys.stderr)
    sys.exit(1)
else:
    new_content = content.replace(old_str, new_str, 1)
    with open(path, 'w') as f:
        f.write(new_content)
    print("Replacement successful in '{}'".format(path))

    diff = difflib.unified_diff(
        content.splitlines(),
        new_content.splitlines(),
        fromfile='before',
        tofile='after',
        lineterm=''
    )
    print("Changes:")
    for line in diff:
        print(line)
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

            # Build the command to execute inside the container
            command = (
                f"echo {bash_single_quote(code_base64)} | base64 -d | "
                f"python3 - {escaped_path} {escaped_old_str_base64} {escaped_new_str_base64}"
            )

            stdout, stderr, returncode = await self.execute_command_in_container(command)
            success = returncode == 0

            if success and not stderr.strip():
                # Update workspace state by reading the new content
                read_cmd = f'cat "{path}"'
                new_content, _, _ = await self.execute_command_in_container(read_cmd)
                await self._update_open_file(path, new_content.strip())
                
                return self.success_response(stdout.strip())
            else:
                return self.fail_response(f"Replace string failed: {stderr.strip()}")

        except Exception as e:
            return self.fail_response(f"Error replacing string: {str(e)}")

    @tool_schema({
        "name": "bash",
        "description": "Execute a shell command in the repository environment with explanatory output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute."},
                "restart": {"type": "boolean", "description": "Whether to restart the bash session.", "default": False}
            },
            "required": ["command"]
        }
    })
    async def bash(self, command: str, restart: bool = False) -> ToolResult:
        """
        Executes an arbitrary bash command with explanatory output.
        
        Parameters:
            command (str): The shell command to execute.
            restart (bool): Whether to restart the bash session.
        
        Returns:
            ToolResult: The result of the bash command execution.
        """
        try:
            if restart:
                self._bash_session.stop()
                self._bash_session = BashSession(self.container_name)
                
            stdout, stderr, returncode = await self._bash_session.execute(command)
            
            # Don't treat warnings as failures
            success = returncode == 0 or (stderr and 'warning:' in stderr.lower())
            
            if success:
                output = stdout
                if stderr:
                    output = f"{output}\nWarnings:\n{stderr}" if output else stderr
                    
                await self._update_terminal(command, output, True)
                return self.success_response(output[:2000])
            else:
                await self._update_terminal(command, stderr, False)
                return self.fail_response(f"Bash command failed: {stderr}")
        
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