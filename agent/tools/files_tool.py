import base64
import asyncio
from agentpress.tool import Tool, ToolResult, tool_schema

class FilesTool(Tool):
    def __init__(self, container_name: str):
        super().__init__()
        self.container_name = container_name

    async def execute_command_in_container(self, command: str):
        full_command = f'. /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed && {command}'
        cmd = ['docker', 'exec', self.container_name, 'bash', '-c', full_command]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return stdout.decode(), stderr.decode(), process.returncode

    @tool_schema({
        "name": "create_file",
        "description": "Create a new file with the provided contents at a given path in the workspace",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to be created."},
                "content": {"type": "string", "description": "The content to write to the file"}
            },
            "required": ["file_path", "content"]
        }
    })
    async def create_file(self, file_path: str, content: str) -> ToolResult:
        try:
            # Check if file exists
            command = f"test -f {file_path}"
            _, _, returncode = await self.execute_command_in_container(command)
            if returncode == 0:
                return self.fail_response(f"File '{file_path}' already exists. Use update_file to modify existing files.")

            # Create directory if needed
            command = f"mkdir -p $(dirname {file_path})"
            _, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Error creating directory: {stderr}")

            # Write content using base64 encoding
            encoded_contents = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            command = f"echo '{encoded_contents}' | base64 -d > {file_path}"
            _, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Error writing file: {stderr}")

            return self.success_response(f"File '{file_path}' created successfully.")
        except Exception as e:
            return self.fail_response(f"Error creating file: {str(e)}")

    @tool_schema({
        "name": "delete_file",
        "description": "Delete a file at the given path in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file to be deleted."}
            },
            "required": ["file_path"]
        }
    })
    async def delete_file(self, file_path: str) -> ToolResult:
        try:
            # Check if file exists
            command = f"test -f {file_path}"
            _, _, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"File '{file_path}' does not exist")

            # Delete the file
            command = f"rm {file_path}"
            _, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Error deleting file: {stderr}")

            return self.success_response(f"File '{file_path}' deleted successfully.")
        except Exception as e:
            return self.fail_response(f"Error deleting file: {str(e)}")

    @tool_schema({
        "name": "str_replace",
        "description": "Replace a string with another string in a file",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file"},
                "old_str": {"type": "string", "description": "String to replace"},
                "new_str": {"type": "string", "description": "Replacement string"}
            },
            "required": ["file_path", "old_str", "new_str"]
        }
    })
    async def str_replace(self, file_path: str, old_str: str, new_str: str) -> ToolResult:
        try:
            # Read file content using base64 to handle large files
            command = f"cat {file_path} | base64"
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            if returncode != 0:
                return self.fail_response(f"Error reading file: {stderr}")

            # Decode base64 content
            content = base64.b64decode(stdout.encode()).decode('utf-8')
            
            occurrences = content.count(old_str)
            if occurrences == 0:
                return self.fail_response(f"String '{old_str}' not found in file")
            if occurrences > 1:
                # Find line numbers using grep
                command = f"grep -n '{old_str}' {file_path}"
                stdout, stderr, returncode = await self.execute_command_in_container(command)
                if returncode != 0:
                    return self.fail_response(f"Error finding string occurrences: {stderr}")
                lines = [line.split(":")[0] for line in stdout.strip().split("\n")]
                return self.fail_response(f"Multiple occurrences found in lines {lines}. Please ensure string is unique")

            # Replace the string
            new_content = content.replace(old_str, new_str)

            # Write new content using base64 to handle large files
            encoded_contents = base64.b64encode(new_content.encode('utf-8')).decode('utf-8')
            
            # Write content in chunks to avoid argument length limits
            chunk_size = 1024 * 64  # 64KB chunks
            for i in range(0, len(encoded_contents), chunk_size):
                chunk = encoded_contents[i:i + chunk_size]
                if i == 0:
                    # First chunk - create new file
                    command = f"echo '{chunk}' | base64 -d > {file_path}"
                else:
                    # Append subsequent chunks
                    command = f"echo '{chunk}' | base64 -d >> {file_path}"
                _, stderr, returncode = await self.execute_command_in_container(command)
                if returncode != 0:
                    return self.fail_response(f"Error writing file chunk: {stderr}")

            return self.success_response(f"Replacement successful in '{file_path}'")

        except Exception as e:
            return self.fail_response(f"Error replacing string: {str(e)}")