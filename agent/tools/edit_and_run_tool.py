import asyncio
import base64
from agentpress.tool import Tool, ToolResult, openapi_schema, xml_schema
from agentpress.state_manager import StateManager
import os
from typing import List, Optional, Literal
from pathlib import Path
from tools.bash_tool import BashTool 

class EditTool(Tool):
    def __init__(self, container_name: str, state_file: str):
        super().__init__()
        self.container_name = container_name
        self.state_manager = StateManager(store_file=state_file)
        self.environment_setup = (
            f'. /opt/miniconda3/etc/profile.d/conda.sh && '
            f'conda activate testbed && '
            f'cd /testbed && '
        )
        self.file_history = {}  # For undo_edit command
        self.bash_tool = BashTool(container_name, state_file)  # Instantiate BashTool

    async def execute_command_in_container(self, command: str):
        """
        Executes a given bash command inside the specified Docker container.

        Parameters:
            command (str): The bash command to execute.

        Returns:
            tuple: (stdout, stderr, returncode)
        """
        full_command = (
            f'{self.environment_setup}'
            f'{command}'
        )
        cmd = [
            'docker', 'exec',
            '-i',  # Interactive mode
            self.container_name,
            '/bin/bash', '-c', full_command
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return stdout.decode(), stderr.decode(), process.returncode

    Command = Literal[
        "create",
        "str_replace",
        "insert",
        "undo_edit",
        "reset",    # Add reset command
    ]

    @xml_schema(
        tag_name="edit-file",
        mappings=[
            {"param_name": "command", "node_type": "attribute", "path": "."},
            {"param_name": "path", "node_type": "attribute", "path": "."},
            {"param_name": "file_text", "node_type": "element", "path": "file_text"},
            {"param_name": "old_str", "node_type": "element", "path": "old_str"},
            {"param_name": "new_str", "node_type": "element", "path": "new_str"},
            {"param_name": "insert_line", "node_type": "element", "path": "insert_line"},
            {"param_name": "bash_command", "node_type": "element", "path": "bash_command"}
        ],
        example='''
        <edit-file command="create" path="/testbed/example.txt">
            <file_text>Hello World!</file_text>
            <bash_command>make build</bash_command>
        </edit-file>
        '''
    )
    @openapi_schema({
        "type": "function",
        "function": {
            "name": "edit_file_and_run",
            "description": (
                "Edit files with commands: 'create', 'str_replace', 'insert', 'undo_edit', 'reset'. "
                "Then, run a bash command after editing.\n"
                "Available commands:\n"
                "- **create**: Create a new file with specified content.\n"
                "- **str_replace**: Replace a unique string in a file.\n"
                "- **insert**: Insert text into a file at a specified line number.\n"
                "- **undo_edit**: Undo the last edit made to a file.\n"
                "- **reset**: Reset file to its state in git HEAD.\n"
                "**Note**: All file paths should be absolute paths starting from the root directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command to execute. One of 'create', 'str_replace', 'insert', 'undo_edit', 'reset'.",
                        "enum": ["create", "str_replace", "insert", "undo_edit", "reset"]
                    },
                    "path": {
                        "type": "string",
                        "description": "The absolute file path to operate on."
                    },
                    "file_text": {
                        "type": ["string", "null"],
                        "description": "The text content for the 'create' command."
                    },
                    "old_str": {
                        "type": ["string", "null"],
                        "description": "The old string to be replaced in 'str_replace' command."
                    },
                    "new_str": {
                        "type": ["string", "null"],
                        "description": "The new string to replace with in 'str_replace' and 'insert' commands."
                    },
                    "insert_line": {
                        "type": ["integer", "null"],
                        "description": "Line number to insert at for 'insert' command (starting from 1)."
                    },
                    "bash_command": {
                        "type": ["string", "null"],
                        "description": "Bash command to run the file after editing e.g (python reproduce_error.py)."
                    },
                },
                "required": ["command", "path", "bash_command"]
            }
        }
    })
    async def edit_file_and_run(self, command: str, path: str, file_text: Optional[str] = None,
                        old_str: Optional[str] = None, new_str: Optional[str] = None,
                        insert_line: Optional[int] = None, bash_command: Optional[str] = None) -> ToolResult:
        """
        **Edit File Tool**

        This tool allows you to perform various file editing operations within the repository environment.

        **Parameters:**
        - `command` (str): The command to execute. Must be one of 'create', 'str_replace', 'insert', 'undo_edit', 'reset'.
        - `path` (str): The absolute file path to operate on.
        - `file_text` (Optional[str]): The text content for 'create' command.
        - `old_str` (Optional[str]): The old string to be replaced in 'str_replace' command.
        - `new_str` (Optional[str]): The new string to replace with in 'str_replace' and 'insert' commands.
        - `insert_line` (Optional[int]): Line number to insert at for 'insert' command (starting from 1).
        - `bash_command` (Optional[str]): Optional bash command to run after editing.

        **Usage Examples:**
        - Create a new file:
          ```json
          {
              "command": "create",
              "path": "/testbed/reproduce_error.py",
              "file_text": "print('Reproducing error')",
              "bash_command": "python reproduce_error.py"
          }
          ```
        - Replace a string in a file:
          ```json
          {
              "command": "str_replace",
              "path": "/testbed/reproduce_error.py",
              "old_str": "print('Old message')",
              "new_str": "print('Reproducing error')",
              "bash_command": "python reproduce_error.py"
          }
          ```
        - Insert text into a file:
          ```json
          {
              "command": "insert",
              "path": "/testbed/reproduce_error.py",
              "insert_line": 2,
              "new_str": "raise Exception('Error reproduced')",
              "bash_command": "python reproduce_error.py"
          }
          ```
        - Undo the last edit:
          ```json
          {
              "command": "undo_edit",
              "path": "/testbed/reproduce_error.py",
              "bash_command": "python reproduce_error.py"
          }
          ```
        - Reset file to its state in git HEAD:
          ```json
          {
              "command": "reset",
              "path": "/testbed/reproduce_error.py",
              "bash_command": "cat reproduce_error.py"
          }
          ```

        **Notes:**
        - All file paths should be absolute paths starting from the root directory.
        - For the 'str_replace' command, the `old_str` must be unique in the file.
        - The 'undo_edit' command supports multiple undos, reversing each prior edit sequentially.
        """
        try:
            if command == "create":
                if file_text is None:
                    return self.fail_response("Parameter 'file_text' is required for the 'create' command.")
                result = await self.create_file(path, file_text)
            elif command == "str_replace":
                if old_str is None or new_str is None:
                    return self.fail_response("Parameters 'old_str' and 'new_str' are required for the 'str_replace' command.")
                result = await self.str_replace(path, old_str, new_str)
            elif command == "insert":
                if insert_line is None or new_str is None:
                    return self.fail_response("Parameters 'insert_line' and 'new_str' are required for the 'insert' command.")
                result = await self.insert_into_file(path, insert_line, new_str)
            elif command == "undo_edit":
                result = await self.undo_edit(path)
            elif command == "reset":
                result = await self.reset_file(path)
            else:
                return self.fail_response(f"Invalid command: {command}")

            if bash_command:
                bash_result = await self.bash_tool.bash_command(bash_command)
                if bash_result.success:
                    result.output += f"\nBash command executed successfully:\n{bash_result.output}"
                else:
                    result.output += f"\nBash command failed:\n{bash_result.output}"

            return result
        except Exception as e:
            return self.fail_response(f"Error executing '{command}': {str(e)}")

    async def create_file(self, path: str, content: str) -> ToolResult:
        """
        Create a new file with the specified content.

        Parameters:
            - `path` (str): The absolute file path to create.
            - `content` (str): The content to write to the new file.

        Returns:
            - `ToolResult`: The result indicating success or failure.
        """
        try:
            # Save current content for undo if file exists
            backup_command = f'cat "{path}"'
            stdout, stderr, returncode = await self.execute_command_in_container(backup_command)
            if returncode == 0:
                self.file_history.setdefault(path, []).append(stdout)

            # Create directory if it doesn't exist
            directory = os.path.dirname(path)
            if directory:
                mkdir_command = f'mkdir -p "{directory}"'
                await self.execute_command_in_container(mkdir_command)

            # Write content to the file
            escaped_content = content.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
            command = f'echo "{escaped_content}" > "{path}"'
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Failed to create file: {stderr.strip()}")

            # Save new content for undo
            self.file_history.setdefault(path, []).append(content)

            return self.success_response(f"File created at {path}")
        except Exception as e:
            return self.fail_response(f"Error creating file: {str(e)}")

    async def str_replace(self, path: str, old_str: str, new_str: str) -> ToolResult:
        """
        Replace a unique occurrence of a string in the specified file with a new string.

        Parameters:
            - `path` (str): The absolute file path to edit.
            - `old_str` (str): The string to be replaced (must be unique in the file).
            - `new_str` (str): The string to replace with.

        Returns:
            - `ToolResult`: The result indicating success or failure.
        """
        try:
            # Read the file content
            command = f'cat "{path}"'
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Failed to read file: {stderr.strip()}")

            content = stdout
            occurrences = content.count(old_str)
            if occurrences == 0:
                return self.fail_response(f"The string '{old_str}' was not found in the file.")
            elif occurrences > 1:
                return self.fail_response(f"The string '{old_str}' was found multiple times in the file. Please ensure it is unique.")

            # Save current content for undo
            self.file_history.setdefault(path, []).append(content)

            # Replace the old string with the new string
            new_content = content.replace(old_str, new_str)

            # Write the new content back to the file
            escaped_content = new_content.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
            command = f'echo "{escaped_content}" > "{path}"'
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Failed to write file: {stderr.strip()}")

            return self.success_response(f"String replaced in {path}")
        except Exception as e:
            return self.fail_response(f"Error replacing string in file: {str(e)}")

    async def insert_into_file(self, path: str, insert_line: int, new_str: str) -> ToolResult:
        """
        Insert a new string into the file at the specified line number.

        Parameters:
            - `path` (str): The absolute file path to edit.
            - `insert_line` (int): The line number to insert at (starting from 1).
            - `new_str` (str): The text to insert.

        Returns:
            - `ToolResult`: The result indicating success or failure.
        """
        try:
            # Read the file content
            command = f'cat "{path}"'
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Failed to read file: {stderr.strip()}")

            lines = stdout.split('\n')
            if insert_line < 1 or insert_line > len(lines) + 1:
                return self.fail_response(f"Parameter 'insert_line' ({insert_line}) is out of bounds.")

            # Save current content for undo
            self.file_history.setdefault(path, []).append(stdout)

            # Insert the new string at the specified line
            lines.insert(insert_line - 1, new_str)
            new_content = '\n'.join(lines)

            # Write the new content back to the file
            escaped_content = new_content.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
            command = f'echo "{escaped_content}" > "{path}"'
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Failed to write file: {stderr.strip()}")

            return self.success_response(f"Inserted text into {path} at line {insert_line}")
        except Exception as e:
            return self.fail_response(f"Error inserting into file: {str(e)}")

    async def undo_edit(self, path: str) -> ToolResult:
        """
        Undo the last edit made to the specified file.

        Parameters:
            - `path` (str): The absolute file path to revert.

        Returns:
            - `ToolResult`: The result indicating success or failure.
        """
        try:
            if path not in self.file_history or not self.file_history[path]:
                return self.fail_response(f"No edits to undo for {path}.")

            # Get the last content from history
            previous_content = self.file_history[path].pop()

            # Write the previous content back to the file
            escaped_content = previous_content.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
            command = f'echo "{escaped_content}" > "{path}"'
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Failed to undo edit: {stderr.strip()}")

            return self.success_response(f"Undo successful for {path}.")
        except Exception as e:
            return self.fail_response(f"Error undoing edit: {str(e)}")

    async def reset_file(self, path: str) -> ToolResult:
        """
        Reset a file to its state in git HEAD.

        Parameters:
            - `path` (str): The absolute file path to reset.

        Returns:
            - `ToolResult`: The result indicating success or failure.
        """
        try:
            relative_path = path.replace('/testbed/', '', 1)
            command = f'git checkout HEAD -- "{relative_path}"'
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Failed to reset file: {stderr.strip()}")

            return self.success_response(f"success reset {path}")
        except Exception as e:
            return self.fail_response(f"Error resetting file: {str(e)}")

