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
                            "checklist_of_tasks": {
                                "type": "array",
                                "description": """Status of tasks:
1. [ ] Explore and find relevant files
2. [ ] Analyze PR description and issue details
3. [ ] Analyze root cause with related files
4. [ ] View existing tests without running them
5. [ ] Consider multiple possible fixes that don't affect existing tests
6. [ ] Choose the best solution which is minimal and precise
7. [ ] Reproduce the error
8. [ ] Implement the fix without affecting other test cases
9. [ ] Handle edge cases
10. [ ] Review existing tests without running them to check for potential regressions
11. [ ] Summarize findings or submit the fix""",
                                "items": {"type": "string"}
                            },
                            "open_folders_and_files_in_code_editor": {
                                "type": "array",
                                "description": "List of important folders, files currently open in editor, including relevant read-only files, edited files and related existing test files",
                                "items": {"type": "string"}
                            },
                            "issue_analysis": {
                                "type": "string",
                                "description": "Describe and analysis of the issue, what you know so far, and what you need to find out",
                            },
                            "thinking_logs": {
                                "type": "array",
                                "description": """Detail of recent actions, trials, and thought process notes: <OBSERVE>...</OBSERVE>\n<REASON>...</REASON>\n<PLAN>...</PLAN>""",
                                "items": {"type": "string"}
                            },
                            "next_steps": {
                                "type": "string",
                                "description": "Suggestion list of next steps to take",
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
    async def summarize(self, workspace_state) -> ToolResult:
        try:
            if isinstance(workspace_state, str):
                workspace_state = json.loads(workspace_state)
            await self.state_manager.set('workspace_state', workspace_state)
            workspace_summary = self.format_workspace_summary(workspace_state)
            
            return self.success_response(
                f"""Workspace state updated:\n<workspace_state>\n{workspace_summary}\n<workspace_state>"""
            )
        except Exception as e:
            return self.fail_response(f"Failed to update workspace state: {str(e)}")

    def format_workspace_summary(self, workspace_state: dict) -> str:
        summary = ""
        for key, value in workspace_state.items():
            summary += f"<{key}>\n"
            if isinstance(value, list):
                summary += '\n'.join(map(str, value))
            else:
                summary += str(value)
            summary += f"\n</{key}>\n\n"
        return summary.strip()
