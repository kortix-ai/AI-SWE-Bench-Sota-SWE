from agentpress.tool import Tool, ToolResult, tool_schema
from agentpress.state_manager import StateManager
import json

class SummaryTool(Tool):
    def __init__(self, state_file: str):
        super().__init__()
        self.state_manager = StateManager(store_file=state_file)

    @tool_schema({
        "name": "summarize",
        "description": "Track and summarize the current workspace state and actions taken.",
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_state": {
                    "type": "object",
                    "description": "Current workspace state information",
                    "properties": {
                        "explorer_folders": {
                            "type": "array",
                            "description": "List of relevant folders",
                            "items": {"type": "string"}
                        },
                        "open_files_in_code_editor": {
                            "type": "array",
                            "description": "List of files currently open in editor, including relevant read-only files and edited files",
                            "items": {"type": "string"}
                        },
                        "thinking_logs": {
                            "type": "array",
                            "description": "Recent actions, trials, and thought process notes, what are suggestions for next steps (remember custom edge cases)",
                            "items": {"type": "string"}
                        },
                        "terminal_session": {
                            "type": "array",
                            "description": "Recent commands and their results or outputs",
                            "items": {"type": "string"}
                        }
                    }
                }
            },
            "required": ["workspace_state"]
        }
    })
    async def summarize(self, workspace_state: dict) -> ToolResult:
        try:
            await self.state_manager.set('workspace_state', workspace_state)
            workspace_summary = self.format_workspace_summary(workspace_state)
            
            return self.success_response(
                f"""Workspace state updated:\n<workspace_state>\n{workspace_summary}\n<workspace_state>"""
            )
        except Exception as e:
            return self.fail_response(f"Failed to update workspace state: {str(e)}")

    def format_workspace_summary(self, workspace_state: dict) -> str:
        return (
            "<explorer_folders>\n" + ', '.join(workspace_state.get('explorer_folders', [])) + "\n</explorer_folders>\n"
            "<open_files_in_code_editor>\n" + '\n'.join(workspace_state.get('open_files_in_code_editor', [])) + "\n</open_files_in_code_editor>\n\n"
            "<thinking_logs>\n" + '\n'.join(workspace_state.get('thinking_logs', [])) + "\n</thinking_logs>\n\n"
            "<terminal_session>\n" + '\n'.join(workspace_state.get('terminal_session', [])) + "\n</terminal_session>\n\n"
        )