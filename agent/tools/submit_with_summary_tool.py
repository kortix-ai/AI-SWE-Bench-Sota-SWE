from agentpress.tool import Tool, ToolResult, tool_schema
from agentpress.state_manager import StateManager
import json

class SubmitWithSummaryTool(Tool):
    def __init__(self, state_file: str):
        super().__init__()
        self.state_manager = StateManager(store_file=state_file)

    @tool_schema({
        "name": "submit_with_summary",
        "description": "Submit the task along with a summary of your discoveries.",
        "parameters": {
            "type": "object",
            "properties": {
                "shared_knowledge": {
                    "type": "string",
                    "description": "A summary of your discoveries, in JSON format."
                }
            },
            "required": ["shared_knowledge"]
        }
    })
    async def submit_with_summary(self, shared_knowledge: str) -> ToolResult:
        try:
            shared_knowledge_data = json.loads(shared_knowledge)
            await self.state_manager.set('shared_knowledge', shared_knowledge_data)
            return self.success_response("Task completed successfully. Shared knowledge saved.\n" + json.dumps(shared_knowledge_data, indent=2))
        except json.JSONDecodeError as e:
            return self.fail_response(f"Invalid JSON format for shared_knowledge: {str(e)}")
