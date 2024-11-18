import asyncio
import base64
from agentpress.tool import Tool, ToolResult, openapi_schema, xml_schema
from agentpress.state_manager import StateManager
import os
from typing import List, Optional
from datetime import datetime

class BashExecutor:
    """Executes bash commands in Docker container using individual exec calls."""
    
    def __init__(self, container_name: str):
        self.container_name = container_name
        
    async def execute(self, command: str) -> tuple[str, str, int]:
        """Execute a command in the container using docker exec."""
        try:
            # Ensure we're in /testbed and have conda environment
            wrapped_command = (
                f'. /opt/miniconda3/etc/profile.d/conda.sh && '
                f'conda activate testbed && '
                f'cd /testbed && '
                f'set -o pipefail && '
                f'{command}'
            )
            
            # Use docker exec directly for each command
            cmd = [
                'docker', 'exec',
                '-i',  # Interactive mode
                self.container_name,
                '/bin/bash', '-c', wrapped_command
            ]
            
            # Execute the command
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wait for command completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=300  # 5 minute timeout
                )
            except asyncio.TimeoutError:
                try:
                    process.terminate()
                except:
                    pass
                return '', 'Command execution timed out after 5 minutes', 1
                
            # Decode outputs
            stdout_str = stdout.decode().strip() if stdout else ''
            stderr_str = stderr.decode().strip() if stderr else ''
            
            # Handle empty output
            if not stdout_str and not stderr_str and process.returncode == 0:
                stdout_str = "Command completed successfully but produced no output"
                
            return stdout_str, stderr_str, process.returncode
            
        except Exception as e:
            return '', f"Error executing command: {str(e)}", 1

class RepositoryTools(Tool):
    def __init__(self, container_name: str, state_file: str):
        super().__init__()
        self.state_manager = StateManager(store_file=state_file)
        self.container_name = container_name
        self._bash_executor = BashExecutor(container_name)
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

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "view",
            "description": (
                "View the contents of a file or list the contents of a directory in the repository with detailed explanations."
            ),
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
        }
    })
    @xml_schema(
        tag_name="view",
        mappings=[
            {"param_name": "paths", "node_type": "attribute", "path": "."},
            {"param_name": "depth", "node_type": "attribute", "path": "."}
        ]
    )
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

def view_path(path: str, depth: int, exclude_patterns: List[str], document_index: int):
    if os.path.isdir(path):
        print(f'<directory index="{document_index}">')
        print(f'<source>{path}</source>')
        print('<contents>')
        for item in list_directory(path, depth, exclude_patterns):
            print(item)
        print('</contents>')
        print('</directory>')
    elif os.path.isfile(path):
        print(f'<document index="{document_index}">')
        print(f'<source>{path}</source>')
        print('<document_content>')
        try:
            with open(path, 'r') as f:
                for i, line in enumerate(f, 1):
                    print(f"{i:6d}\t{line}", end='')
        except Exception as e:
            print(f"Error reading file {path}: {str(e)}", file=sys.stderr)
        print('</document_content>')
        print('</document>')
    else:
        print(f"The path '{path}' is neither a file nor a directory.", file=sys.stderr)

def main():
    paths = sys.argv[1].split(',')
    exclude_patterns = sys.argv[2].split(',')
    depth = int(sys.argv[3])
    print('<documents>')
    for idx, path in enumerate(paths, 1):
        view_path(path.strip(), depth, exclude_patterns, idx)
    print('</documents>')

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

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "submit",
            "description": "If all test files is working including edge cases and you are confident that the issue is resolve, submit the fix.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    })
    @xml_schema(
        tag_name="submit",
        mappings=[]
    )
    async def submit(self) -> ToolResult:
        """
        Signals that the task is completed.

        Returns:
            ToolResult: Success message indicating task completion.
        """
        return self.success_response("Task completed successfully.")
