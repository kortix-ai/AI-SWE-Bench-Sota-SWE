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
    def __init__(self, container_name: str, state_manager: StateManager):
        super().__init__()
        self.state_manager = state_manager
        self.container_name = container_name
        self._bash_executor = BashExecutor(container_name)

    async def _init_workspace(self):
        """Initialize the workspace state with empty structures if not already initialized."""
        workspace = await self.state_manager.get("workspace")
        if workspace is None:
            workspace = {
                "open_items": {},          # open_folders and open_files
                "terminal_session": [],    # Current terminal session output (last N commands)
                "thinking_logs": [],        # Logs for internal thoughts or notes
            }
            await self.state_manager.set("workspace", workspace)

    async def _update_open_item(self, path: str, content: str):
        """Update or add an item in the open items list."""
        workspace = await self.state_manager.get("workspace")
        workspace["open_items"][path] = {
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

    async def format_workspace_xml(self) -> str:
        """Format the workspace into an XML string for the Agent."""
        workspace = await self.state_manager.get("workspace")
        xml_output = "<workspace>\n"
        for path, item in workspace["open_items"].items():
            xml_output += f"{item['content']}\n"
        xml_output += "</workspace>"
        return xml_output

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "view_folder",
            "description": (
                "List the contents of a directory in the repository with detailed explanations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The directory path to view."
                    },
                    "depth": {
                        "type": "integer",
                        "description": "The maximum directory depth to search for contents.",
                        "default": 3
                    },
                },
                "required": ["path"]
            }
        }
    })
    @xml_schema(
        tag_name="view_folder",
        mappings=[
            {"param_name": "path", "node_type": "attribute", "path": "path"},
            {"param_name": "depth", "node_type": "attribute", "path": "depth"}
        ],
        example='''
        <!-- Repository View Folder Tool -->
        <!-- List directory contents with detailed explanations -->
        
        <!-- Parameters Description:
             - path: Directory path to view (REQUIRED)
             - depth: Maximum directory depth to search for contents (optional)
        -->

        <!-- View directory contents with depth -->
        <view_folder path="/testbed" depth="3" />

        <!-- Important Notes:
             - Path should be absolute path from repository root
             - Hidden files and directories are automatically excluded
             - Common exclude patterns: .rst, .pyc files
             - Directory listings are sorted alphabetically
        -->
        '''
    )
    async def view_folder(self, path: str, exclude_patterns: list = ['.rst', '.pyc'], depth: Optional[int] = 3) -> ToolResult:
        try:
            # Convert to list with single path for compatibility with existing code
            paths = [path]
            
            # Set depth to 1 for files, use provided depth or default 3 for directories
            if os.path.isfile(path):
                depth = 1
            else:
                depth = depth or 3
            
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
        print('</directory>')
    elif os.path.isfile(path):
        print(f'<file path="{path}">')
        try:
            with open(path, 'r') as f:
                for i, line in enumerate(f, 1):
                    print(f"{i:6d}\t{line}", end='')
        except Exception as e:
            print(f"Error reading file {path}: {str(e)}", file=sys.stderr)
        print('</file>')
    else:
        print(f"The path '{path}' is neither a file nor a directory.", file=sys.stderr)

def main():
    path = sys.argv[1]
    exclude_patterns = sys.argv[2].split(',')
    depth = int(sys.argv[3])
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
                # Update open_items with the content
                await self._update_open_item(path, stdout.strip())
                return self.success_response(stdout.strip())
            else:
                return self.fail_response(f"View command failed: {stderr.strip()}")
        
        except Exception as e:
            return self.fail_response(f"Error executing view command: {str(e)}")

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "submit",
            "description": "If all test files is working including edge cases, and existings tests and you are confident that the issue is resolve, submit the fix.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    })
    @xml_schema(
        tag_name="submit",
        mappings=[],
        example='''
        <!-- Repository Submit Tool -->
        <!-- Submit the fix when all tests pass and the issue is resolved -->
        
        <!-- No Parameters Required -->
        
        <!-- Submit the completed fix -->
        <submit />

        <!-- Important Notes:
             - Only use when all test files are working
             - Ensure edge cases are covered
             - Verify existing tests pass
             - Be confident the issue is fully resolved
             - This marks the task as completed
        -->
        '''
    )
    async def submit(self, ) -> ToolResult:
        """
        Signals that the task is completed.

        Returns:
            ToolResult: Success message indicating task completion.
        """
        return self.success_response("Task completed successfully.")

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "open_file",
            "description": "Open a file and add its content to the workspace state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The file path to open."},
                },
                "required": ["path"]
            }
        }
    })
    @xml_schema(
        tag_name="open_file",
        mappings=[{"param_name": "path", "node_type": "attribute", "path": "."}],
        example='''
        <!-- Open File Tool -->
        <!-- Open a file and add its content to the workspace state -->
        
        <!-- Parameters:
             - path: The file path to open (REQUIRED)
        -->
        <open_file path="/testbed/.../example.py" />
        '''
    )
    async def open_item(self, path: str) -> ToolResult:
        """Open an item and add its content to the workspace state."""
        try:
            command = f"cat {path}"
            stdout, stderr, returncode = await self._bash_executor.execute(command)
            if returncode == 0:
                # Format output with tags
                formatted_output = f'<file path="{path}">\n{stdout}\n</file>'
                await self._update_open_item(path, formatted_output)
                return self.success_response(formatted_output)
            else:
                return self.fail_response(f"Failed to open item {path}: {stderr}")
        except Exception as e:
            return self.fail_response(f"Error opening item {path}: {str(e)}")

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "close_file",
            "description": "Close a file and remove its content from the workspace state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The file path to close."},
                },
                "required": ["path"]
            }
        }
    })
    @xml_schema(
        tag_name="close_file",
        mappings=[{"param_name": "path", "node_type": "attribute", "path": "."}],
        example='''
        <!-- Close File Tool -->
        <!-- Close a file and remove its content from the workspace state -->
        
        <!-- Parameters:
             - path: The file path to close (REQUIRED)
        -->
        <close_file path="/testbed/.../example.py" />
        '''
    )
    async def close_item(self, path: str) -> ToolResult:
        try:
            workspace = await self.state_manager.get("workspace")
            if path in workspace["open_items"]:
                del workspace["open_items"][path]
                await self.state_manager.set("workspace", workspace)
                return self.success_response(f"Item {path} closed successfully.")
            else:
                return self.fail_response(f"Item {path} is not open.")
        except Exception as e:
            return self.fail_response(f"Error closing item {path}: {str(e)}")

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file with the specified content and add it to the workspace state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The file path to create."},
                    "content": {"type": "string", "description": "The content to write into the file."}
                },
                "required": ["path", "content"]
            }
        }
    })
    @xml_schema(
        tag_name="create_file",
        mappings=[
            {"param_name": "path", "node_type": "attribute", "path": "."},
            {"param_name": "content", "node_type": "text", "path": "."}
        ],
        example='''
        <!-- Create File Tool -->
        <!-- Create a new file with specified content -->
        
        <!-- Parameters:
             - path: The file path to create (REQUIRED)
             - content: The content to write into the file (REQUIRED)
        -->
        <create_file path="/testbed/src/new_file.py">
        print("Hello, World!")
        </create_file>
        '''
    )
    async def create_file(self, path: str, content: str) -> ToolResult:
        try:
            encoded_content = base64.b64encode(content.encode()).decode()
            command = f"echo {encoded_content} | base64 -d > {path}"
            stdout, stderr, returncode = await self._bash_executor.execute(command)
            if returncode == 0:
                await self._update_open_item(path, content)
                return self.success_response(f"File {path} created successfully.")
            else:
                return self.fail_response(f"Failed to create file {path}: {stderr}")
        except Exception as e:
            return self.fail_response(f"Error creating file {path}: {str(e)}")

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit an existing file by replacing specified strings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The file path to edit."},
                    "replacements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"}
                            },
                            "required": ["old_string", "new_string"]
                        },
                        "description": "List of string replacements to perform."
                    }
                },
                "required": ["path", "replacements"]
            }
        }
    })
    @xml_schema(
        tag_name="edit_file",
        mappings=[
            {"param_name": "path", "node_type": "attribute", "path": "."},
            {"param_name": "replacements", "node_type": "child", "path": "."}
        ],
        example='''
        <!-- Edit File Tool -->
        <!-- Edit an existing file by replacing specified strings -->
        
        <!-- Parameters:
             - path: The file path to edit (REQUIRED)
             - replacements: List of string replacements (REQUIRED)
        -->
        <edit_file path="/testbed/.../example.py">
            <replacements>
                <replacement>
                    <old_string>foo</old_string>
                    <new_string>bar</new_string>
                </replacement>
                <replacement>
                    <old_string>hello</old_string>
                    <new_string>world</new_string>
                </replacement>
            </replacements>
        </edit_file>
        '''
    )
    async def edit_item(self, path: str, replacements: List[dict]) -> ToolResult:
        try:
            workspace = await self.state_manager.get("workspace")
            if path in workspace["open_items"]:
                content = workspace["open_items"][path]["content"]
                for rep in replacements:
                    old_string = rep.get("old_string")
                    new_string = rep.get("new_string")
                    content = content.replace(old_string, new_string)
                # Update the file content in the container
                encoded_content = base64.b64encode(content.encode()).decode()
                command = f"echo {encoded_content} | base64 -d > {path}"
                stdout, stderr, returncode = await self._bash_executor.execute(command)
                if returncode == 0:
                    await self._update_open_item(path, content)
                    return self.success_response(f"Item {path} edited successfully.")
                else:
                    return self.fail_response(f"Failed to edit item {path}: {stderr}")
            else:
                return self.fail_response(f"Item {path} is not open.")
        except Exception as e:
            return self.fail_response(f"Error editing item {path}: {str(e)}")

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command in the terminal and update the workspace state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute."}
                },
                "required": ["command"]
            }
        }
    })
    @xml_schema(
        tag_name="run_command",
        mappings=[{"param_name": "command", "node_type": "text", "path": "."}],
        example='''
        <!-- Run Command Tool -->
        <!-- Run a shell command in the terminal -->
        
        <!-- Parameters:
             - command: The shell command to execute (REQUIRED)
        -->
        <run_command>
        ls -la /testbed/src
        </run_command>
        '''
    )
    async def run_command(self, command: str) -> ToolResult:
        try:
            stdout, stderr, returncode = await self._bash_executor.execute(command)
            success = returncode == 0
            await self._update_terminal(command, stdout + stderr, success)
            if success:
                return self.success_response(f"Command executed successfully:\n{stdout}")
            else:
                return self.fail_response(f"Command failed with error:\n{stderr}")
        except Exception as e:
            return self.fail_response(f"Error executing command: {str(e)}")