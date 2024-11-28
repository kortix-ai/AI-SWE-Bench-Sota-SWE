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
                "open_folders": {},        # Dictionary with folder paths as keys and depths as values
                "open_files": [],          # List of paths to open files
                "terminal_session": [],    # Current terminal session output (last N commands)
                "thinking_logs": [],       # Logs for internal thoughts or notes
            }
            # Add initial view of /testbed with default depth of 3
            workspace["open_folders"]["/testbed"] = 3
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
        # Include content from open folders with their specified depths
        for path, depth in workspace["open_folders"].items():
            result = await self.view_folder(path=path, depth=depth)
            if result.success:
                xml_output += f"{result.output}\n"
        # Include content from open files
        for file_path in workspace["open_files"]:
            command = f"cat {file_path}"
            stdout, stderr, returncode = await self._bash_executor.execute(command)
            if returncode == 0:
                xml_output += f'<file path="{file_path}">\n{stdout}\n</file>\n'
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
                # No need to update open_items anymore, just return the output
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
            "description": "Open a file or folder and add it to the workspace state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The file or folder path to open."},
                    "depth": {
                        "type": "integer",
                        "description": "The maximum directory depth to search for contents (only for folders).",
                        "default": 3
                    },
                },
                "required": ["path"]
            }
        }
    })
    @xml_schema(
        tag_name="open_file",
        mappings=[
            {"param_name": "path", "node_type": "attribute", "path": "."},
            {"param_name": "depth", "node_type": "attribute", "path": "."},
        ],
        example='''
        <!-- Open File or Folder Tool -->
        <!-- Open a file or folder and add it to the workspace state -->
        
        <!-- Parameters:
             - path: The file or folder path to open (REQUIRED)
             - depth: Maximum depth for folders (optional, default is 3)
        -->
        <open_file path="/testbed" depth="3" />
        '''
    )
    async def open_item(self, path: str, depth: int = 3) -> ToolResult:
        """Open an item and add its content to the workspace state."""
        try:
            workspace = await self.state_manager.get("workspace")
            # Determine if the path is a file or directory
            command = f"if [ -d '{path}' ]; then echo 'directory'; elif [ -f '{path}' ]; then echo 'file'; else echo 'none'; fi"
            stdout, stderr, returncode = await self._bash_executor.execute(command)
            if returncode == 0:
                item_type = stdout.strip()
                if item_type == 'directory':
                    # Add or update the folder with its depth
                    workspace["open_folders"][path] = depth
                    await self.state_manager.set("workspace", workspace)
                    return self.success_response(f"Folder {path} opened with depth {depth} successfully.")
                elif item_type == 'file':
                    if path not in workspace["open_files"]:
                        workspace["open_files"].append(path)
                        await self.state_manager.set("workspace", workspace)
                    return self.success_response(f"File {path} opened successfully.")
                else:
                    return self.fail_response(f"Path {path} does not exist.")
            else:
                return self.fail_response(f"Failed to determine item type for {path}: {stderr}")
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
        """Close a file or folder by removing its path from the workspace."""
        try:
            workspace = await self.state_manager.get("workspace")
            if path in workspace["open_folders"]:
                del workspace["open_folders"][path]
                await self.state_manager.set("workspace", workspace)
                return self.success_response(f"Folder {path} closed successfully.")
            elif path in workspace["open_files"]:
                workspace["open_files"].remove(path)
                await self.state_manager.set("workspace", workspace)
                return self.success_response(f"File {path} closed successfully.")
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
                # Add to open_files instead of open_items
                workspace = await self.state_manager.get("workspace")
                if path not in workspace["open_files"]:
                    workspace["open_files"].append(path)
                    await self.state_manager.set("workspace", workspace)
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
            {"param_name": "replacements", "node_type": "element", "path": "replacements"}
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
    async def edit_file(self, path: str, replacements: dict) -> ToolResult:
        """Edit an existing file by replacing specified strings."""
        try:
            workspace = await self.state_manager.get("workspace")
            if path in workspace["open_files"]:
                # Read the current content from the file system
                command = f"cat {path}"
                stdout, stderr, returncode = await self._bash_executor.execute(command)
                if returncode != 0:
                    return self.fail_response(f"Failed to read file {path}: {stderr}")
                content = stdout
                
                # Ensure replacements is a list of replacement objects
                if isinstance(replacements, dict):
                    # Handle single replacement from XML parsing
                    if 'replacement' in replacements:
                        replacements_list = replacements['replacement']
                        if isinstance(replacements_list, dict):
                            replacements_list = [replacements_list]
                    else:
                        # Direct dictionary case
                        replacements_list = [replacements]
                elif isinstance(replacements, list):
                    replacements_list = replacements
                else:
                    return self.fail_response("Invalid replacements format")

                # Apply all replacements
                for rep in replacements_list:
                    if isinstance(rep, dict) and 'old_string' in rep and 'new_string' in rep:
                        old_string = rep['old_string'][0]
                        new_string = rep['new_string'][0]
                        content = content.replace(old_string, new_string)
                    else:
                        return self.fail_response("Invalid replacement format")
                # Write the updated content back to the file
                encoded_content = base64.b64encode(content.encode()).decode()
                command = f"echo {encoded_content} | base64 -d > {path}"
                stdout, stderr, returncode = await self._bash_executor.execute(command)
                if returncode == 0:
                    return self.success_response(f"File {path} edited successfully.")
                else:
                    return self.fail_response(f"Failed to write to file {path}: {stderr}")
            else:
                return self.fail_response(f"File {path} is not open.")
        except Exception as e:
            return self.fail_response(f"Error editing file {path}: {str(e)}")

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
