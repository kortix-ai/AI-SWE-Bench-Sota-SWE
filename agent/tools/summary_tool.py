from agentpress.tool import Tool, ToolResult, openapi_schema, xml_schema
from agentpress.state_manager import StateManager
import json

class SummaryTool(Tool):
    def __init__(self, state_file: str):
        super().__init__()
        self.state_manager = StateManager(store_file=state_file)

    @openapi_schema({
        "type": "function",
        "function": {
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
                                "description": "Detail of recent actions, trials, and thought process notes",
                                "items": {"type": "string"}
                            },
                            "test_commands": {
                                "type": "array",
                                "description": "List of test commands to execute (e.g ['python reproduce_error.py'])",
                                "items": {"type": "string"}
                            }
                        }
                    }
                },
                "required": ["workspace_state"]
            }
        }
    })
    @xml_schema(
        tag_name="summarize",
        mappings=[
            {"param_name": "workspace_state", "node_type": "content", "path": "."}
        ]
    )
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
            "<test_commands>\n" + '\n'.join(workspace_state.get('test_commands', [])) + "\n</test_commands>\n\n"
        )
