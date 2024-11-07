import os
import asyncio
import subprocess
from agentpress.tool import Tool, ToolResult, tool_schema
from agentpress.state_manager import StateManager

class TerminalTool(Tool):
    def __init__(self, repo_path: str):
        super().__init__()
        self.state_manager = StateManager(store_file="/tmp/agentpress/state.json")
        self.repo_path = repo_path
        self.workspace = self.repo_path
        os.makedirs(self.workspace, exist_ok=True)
        asyncio.create_task(self._init_workspace())
        
    async def _init_workspace(self):
        """Initialize workspace state"""
        await self.state_manager.set("workspace_path", self.workspace)
        
    async def _update_command_history(self, command: str, output: str, success: bool):
        """Update command history in state"""
        history = await self.state_manager.get("terminal_history") or []
        history.append({
            "command": command,
            "output": output,
            "success": success,
            "cwd": os.path.relpath(os.getcwd(), self.workspace)
        })
        await self.state_manager.set("terminal_history", history)

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
        original_dir = os.getcwd()
        try:
            # Always change to workspace directory before executing
            os.chdir(self.workspace)
            
            # Execute command
            print(f"Executing command: {command} at {self.workspace}")
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace  # Explicitly set working directory
            )
            stdout, stderr = await process.communicate()
            
            # Prepare output
            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""
            success = process.returncode == 0
            
            # Update state with command history
            await self._update_command_history(
                command=command,
                output=output + error,
                success=success
            )
            
            if success:
                return self.success_response({
                    "output": output,
                    "error": error,
                    "exit_code": process.returncode,
                    "cwd": self.workspace
                })
            else:
                return self.fail_response(f"Command failed with exit code {process.returncode}: {error}")
                
        except Exception as e:
            await self._update_command_history(
                command=command,
                output=str(e),
                success=False
            )
            return self.fail_response(f"Error executing command: {str(e)}")
        finally:
            # Always restore original directory
            os.chdir(original_dir)
