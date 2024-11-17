# agent/tools/bash_tool.py

import asyncio
from agentpress.tool import Tool, ToolResult, tool_schema
from agentpress.state_manager import StateManager

class BashTool(Tool):
    def __init__(self, container_name: str, state_file: str):
        super().__init__()
        self.container_name = container_name
        self.state_manager = StateManager(store_file=state_file)
        self.environment_setup = (
            f'. /opt/miniconda3/etc/profile.d/conda.sh && '
            f'conda activate testbed && '
            f'cd /testbed && '
        )

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
            f'set -o pipefail && '
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
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)  # 5 minutes timeout
        except asyncio.TimeoutError:
            process.kill()
            return '', 'Command execution timed out after 5 minutes', 1
        return stdout.decode(), stderr.decode(), process.returncode

    @tool_schema({
        "name": "bash_command",
        "description": (
            "Execute a bash shell command in the repository environment with explanatory output.\n"
            "**Notes:**\n"
            "- The working directory is `/testbed`.\n"
            "- The environment is set up with `conda activate testbed`.\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute."},
            },
            "required": ["command"]
        }
    })
    async def bash_command(self, command: str) -> ToolResult:
        try:
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            if returncode == 0:
                output = stdout.strip() if stdout.strip() else "Command executed successfully but produced no output."
                return self.success_response(output)
            else:
                error_output = stderr.strip() if stderr.strip() else "Unknown error occurred."
                return self.fail_response(f"Command failed with error: {error_output}")
        except Exception as e:
            return self.fail_response(f"Error executing bash command: {str(e)}")
