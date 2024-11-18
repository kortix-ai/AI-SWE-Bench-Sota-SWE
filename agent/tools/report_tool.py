from agentpress.tool import Tool, ToolResult, openapi_schema, xml_schema
from agentpress.state_manager import StateManager
import json

class ReportTool(Tool):
    def __init__(self, state_file: str):
        super().__init__()
        self.state_manager = StateManager(store_file=state_file)

    @openapi_schema({
        "type": "function",
        "function": {
            "name": "report",
            "description": "Track and report the current workspace state and actions taken.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace_state": {
                        "type": "object",
                        "description": "Current workspace state information",
                        "properties": {
                            "open_folders" : {
                                "type": "array",
                                "description": "List of important folders related to the issue",
                                "items": {"type": "string"}
                            },
                            "checklist_of_tasks": {
                                "type": "array",
                                "description": """Status of tasks:
1. [ ] Explore and find the root cause
2. [ ] Expand the search scope to related files 
3. [ ] Analyze PR description and issue details
4. [ ] Analyze root cause with related files
5. [ ] View existing tests without running them
6. [ ] Consider multiple possible fixes that don't affect existing tests
7. [ ] Choose the best solution which is minimal and precise
8. [ ] Reproduce the error
9. [ ] Implement the fix without affecting other test cases
10. [ ] Handle edge cases
11. [ ] Review existing tests without running them to check for potential regressions
12. [ ] Submit the fix if all tasks are completed, otherwise summarize findings""",
                                "items": {"type": "string"}
                            },
                            "open_files_in_code_editor": {
                                "type": "array",
                                "description": "List of important files currently open in editor, including relevant read-only files, edited files and related existing test files",
                                "items": {"type": "string"}
                            },
                            "issue_analysis": {
                                "type": "string",
                                "description": "Describe and analysis of the issue, what you know so far, and what you need to find out",
                            },
                            "detail_logs": {
                                "type": "array",
                                "description": """Detail of reasoning, proposed solutions, solutions tried, ... All the information that make your work worth it, and useful for the next generation""",
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
        tag_name="report",
        mappings=[
            {"param_name": "workspace_state", "node_type": "content", "path": "."}
        ]
    )
    async def report(self, workspace_state) -> ToolResult:
        try:
            # Handle string input by parsing as JSON
            if isinstance(workspace_state, str):
                workspace_state = json.loads(workspace_state)
            
            # If there's a nested workspace_state, use that instead
            if isinstance(workspace_state, dict) and 'workspace_state' in workspace_state:
                workspace_state = workspace_state['workspace_state']
            
            # Validate the workspace state structure
            if not isinstance(workspace_state, dict):
                return self.fail_response("Workspace state must be a dictionary")

            # Update the state
            await self.state_manager.set('workspace_state', workspace_state)
            workspace_report = self.format_workspace_report(workspace_state)
            
            return self.success_response(
                f"""Workspace state updated:\n<workspace_state>\n{workspace_report}\n</workspace_state>"""
            )
        except json.JSONDecodeError as e:
            return self.fail_response(f"Invalid JSON format: {str(e)}")
        except Exception as e:
            return self.fail_response(f"Failed to update workspace state: {str(e)}")

    def format_workspace_report(self, workspace_state: dict) -> str:
        summary = ""
        for key, value in workspace_state.items():
            summary += f"<{key}>\n"
            if isinstance(value, list):
                summary += '\n'.join(map(str, value))
            else:
                summary += str(value)
            summary += f"\n</{key}>\n\n"
        return summary.strip()