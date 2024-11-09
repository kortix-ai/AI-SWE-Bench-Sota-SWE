import asyncio
from agentpress.tool import Tool, ToolResult, tool_schema
from agentpress.state_manager import StateManager

class TerminalTool(Tool):
    def __init__(self, container_name: str):
        super().__init__()
        self.state_manager = StateManager(store_file="state.json")
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
        "name": "execute_command",
        "description": "Execute a shell command in the workspace directory",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to execute"},
            },
            "required": ["command"]
        }
    })
    async def execute_command(self, command: str) -> ToolResult:
        try:
            stdout, stderr, returncode = await self.execute_command_in_container(command)
            success = returncode == 0

            history = await self.state_manager.get("terminal_history") or []
            history.append({
                "command": command,
                "output": stdout + stderr,
                "success": success,
            })
            await self.state_manager.set("terminal_history", history)

            if success:
                return self.success_response({
                    "output": stdout,
                    "error": stderr,
                    "exit_code": returncode,
                })
            else:
                return self.fail_response(f"Command failed with exit code {returncode}: {stderr}")

        except Exception as e:
            return self.fail_response(f"Error executing command: {str(e)}")
