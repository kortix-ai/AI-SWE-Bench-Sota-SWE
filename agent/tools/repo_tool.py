import asyncio
from agentpress.tool import Tool, ToolResult, tool_schema
from agentpress.state_manager import StateManager
import os

class RepositoryTools(Tool):
    def __init__(self, container_name: str):
        super().__init__()
        self.state_manager = StateManager(store_file="state.json")
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
                "path": {"type": "string", "description": "The file or directory path to view."},
                "exclude_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns of files to exclude from directory listings."
                },
            },
            "required": ["path"]
        }
    })
    async def view(self, path: str, exclude_patterns: list = []) -> ToolResult:
        """
        Views the contents of a file or lists the contents of a directory with detailed explanations.
        
        Parameters:
            path (str): The file or directory path to view.
            exclude_patterns (list): Patterns of files to exclude from directory listings.
        
        Returns:
            ToolResult: The result of the view operation.
        """
        try:
            # Construct exclusion patterns for find command
            exclude_flags = ""
            for pattern in exclude_patterns:
                exclude_flags += f' ! -name "{pattern}"'
            
            # Single bash command to handle both file and directory
            command = (
                f'if [ -d "{path}" ]; then '
                f'echo "Here\'s the files and directories up to 2 levels deep in {path}, excluding hidden items and patterns {exclude_patterns}:"; '
                f'find "{path}" -maxdepth 2 {exclude_flags} ! -path "*/\\.*" -print; '
                f'elif [ -f "{path}" ]; then '
                f'echo "Here\'s the result of running `cat -n` on {path}:"; '
                f'cat -n "{path}"; '
                f'else '
                f'echo "The path \'{path}\' is neither a file nor a directory." >&2; '
                f'fi'
            )
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            success = returncode == 0

            history_key = "view_history"
            history = await self.state_manager.get(history_key) or []
            history.append({
                "path": path,
                "exclude_patterns": exclude_patterns,
                "output": stdout + stderr,
                "success": success,
            })
            await self.state_manager.set(history_key, history)

            if success and not stderr.strip():
                return self.success_response({
                    "output": stdout.strip(),
                    "error": stderr.strip(),
                    "exit_code": returncode,
                })
            else:
                return self.fail_response(f"View command failed: {stderr.strip()}")
        
        except Exception as e:
            return self.fail_response(f"Error executing view command: {str(e)}")

    @tool_schema({
        "name": "create_file",
        "description": "Create a new file with specified content in the repository.",
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
        """
        Creates a new file with the specified content.
        
        Parameters:
            path (str): The file path to create.
            content (str): The content to write to the file.
        
        Returns:
            ToolResult: The result of the create file operation.
        """
        try:
            # Single command to create the file with proper escaping and content
            # Uses printf for better handling of special characters and multi-line content
            escaped_content = content.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
            command = (
                f'printf "%s" "{escaped_content}" > "{path}" && '
                f'echo "File created at {path}"'
            )
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            success = returncode == 0

            history = await self.state_manager.get("create_file_history") or []
            history.append({
                "path": path,
                "content": content,
                "output": stdout + stderr,
                "success": success,
            })
            await self.state_manager.set("create_file_history", history)

            if success and not stderr.strip():
                message = stdout.strip() if stdout else f"File created at {path}"
                return self.success_response({
                    "message": message,
                    "exit_code": returncode,
                })
            else:
                return self.fail_response(f"Create file command failed: {stderr.strip()}")
        
        except Exception as e:
            return self.fail_response(f"Error creating file: {str(e)}")

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
            # Single command to perform in-place replacement with proper escaping
            escaped_old = old_str.replace('/', '\\/').replace('"', '\\"').replace("'", "\\'")
            escaped_new = new_str.replace('/', '\\/').replace('"', '\\"').replace("'", "\\'")
            # Using sed with proper escaping and echo for descriptive output
            command = (
                f"sed -i 's/{escaped_old}/{escaped_new}/g' \"{path}\" && "
                f'echo "Replaced \'{old_str}\' with \'{new_str}\' in {path}"'
            )
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            success = returncode == 0

            history = await self.state_manager.get("replace_string_history") or []
            history.append({
                "path": path,
                "old_str": old_str,
                "new_str": new_str,
                "output": stdout + stderr,
                "success": success,
            })
            await self.state_manager.set("replace_string_history", history)

            if success and not stderr.strip():
                message = stdout.strip() if stdout else f"Replaced '{old_str}' with '{new_str}' in {path}"
                return self.success_response({
                    "message": message,
                    "exit_code": returncode,
                })
            else:
                return self.fail_response(f"Replace string command failed: {stderr.strip()}")
        
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
            # Single command execution with descriptive output
            full_command = (
                f'echo "Here\'s the result of running `{command}`:"; '
                f'{command}'
            )
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

            if success and not stderr.strip():
                return self.success_response({
                    "output": stdout.strip(),
                    "error": stderr.strip(),
                    "exit_code": returncode,
                })
            else:
                return self.fail_response(f"Bash command failed: {stderr.strip()}")
        
        except Exception as e:
            return self.fail_response(f"Error executing bash command: {str(e)}")
