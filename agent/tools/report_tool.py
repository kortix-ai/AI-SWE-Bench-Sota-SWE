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
            "description": "Track and report the current workspace state and actions taken. You should review all actions you've taken and the current state of the workspace before submitting the report. E.g have you use <REVIEW> to ensure all changes are consistent and correct?",
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
1. [ ] Explore `/testbed` and find relevant files.
2. [ ] Analyze PR description and issue details.
3. [ ] Examine related files and understand code patterns, relevant functions.
4. [ ] Analyze root cause with related files.
5. [ ] Consider multiple possible solutions, propose solutions, and pick the best one.
6. [ ] Implement the fix directly, updating related parts of the code accordingly.
7. [ ] Use 'run_pytest' tool to run existing tests and verify no regressions.
8. [ ] Create 'reproduce_error.py' and 'edge_cases.py' to test if the fix is working and to handle edge cases.
9. [ ] Review modified files and identify any dependent code that needs updates.
10. [ ] Use "view" edited files again, and <REVIEW> to ensure all changes are consistent and correct.
11. [ ] Report findings or submit the fix.""",
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
                                "description": """Detail of reasoning, proposed solutions, solutions tried, ... All the information that make your work worth it, and useful for the next generation. Make it very details.""",
                                "items": {"type": "string"}
                            },
                            "analysis_code_patterns": {
                                "type": "string",
                                "description": "Analysis of code patterns, functions of relevant files",
                            },
                            "proposed_solutions": {
                                "type": "array",
                                "description": """A list of proposed solutions to the issue, applied or not. e.g [tried, not working]""",
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
                try:
                    # Clean up the input string if needed
                    workspace_state = workspace_state.strip()
                    # Try parsing as regular JSON first
                    try:
                        workspace_state = json.loads(workspace_state)
                    except json.JSONDecodeError:
                        # Use JSONDecoder for more lenient parsing if regular parsing fails
                        decoder = json.JSONDecoder()
                        workspace_state, _ = decoder.raw_decode(workspace_state)
                except Exception as e:
                    return self.fail_response(f"Invalid JSON format: {str(e)}")
            
            # Handle nested workspace_state structure
            if isinstance(workspace_state, dict):
                if 'workspace_state' in workspace_state:
                    workspace_state = workspace_state['workspace_state']
                elif 'function' in workspace_state and isinstance(workspace_state['function'], dict):
                    # Handle function call format
                    try:
                        args = json.loads(workspace_state['function'].get('arguments', '{}'))
                        workspace_state = args.get('workspace_state', {})
                    except Exception:
                        return self.fail_response("Invalid function arguments format")

            # Validate the workspace state structure
            if not isinstance(workspace_state, dict):
                return self.fail_response("Workspace state must be a dictionary")

            # Update the state
            await self.state_manager.set('workspace_state', workspace_state)
            workspace_report = self.format_workspace_report(workspace_state)
            
            return self.success_response(
                f"""Workspace state updated:\n<workspace_state>\n{workspace_report}\n</workspace_state>"""
            )
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