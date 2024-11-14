from agentpress.tool import Tool, ToolResult, tool_schema
from agentpress.state_manager import StateManager
from typing import Any

class SharedKnowledgeTool(Tool):
    def __init__(self, state_file: str):
        super().__init__()
        self.state_manager = StateManager(store_file=state_file)

    @tool_schema({
        "name": "add_to_shared_knowledge",
        "description": "Add an item to a list in shared_knowledge.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key in shared_knowledge (must be a list)."},
                "item": {"type": "string", "description": "The item to add to the list."},
            },
            "required": ["key", "item"]
        }
    })
    async def add_to_shared_knowledge(self, key: str, item: str) -> ToolResult:
        try:
            shared_knowledge = await self.state_manager.get('shared_knowledge') or {}
            if key not in shared_knowledge or not isinstance(shared_knowledge[key], list):
                return self.fail_response(f"Key '{key}' is not a list in shared_knowledge.")
            shared_knowledge[key].append(item)
            await self.state_manager.set('shared_knowledge', shared_knowledge)
            return self.success_response(f"Item added to shared_knowledge[{key}].")
        except Exception as e:
            return self.fail_response(f"Error adding to shared_knowledge: {str(e)}")

    @tool_schema({
        "name": "update_shared_knowledge", 
        "description": "Update a value in shared_knowledge.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key in shared_knowledge."},
                "value": {"type": "string", "description": "The value to set for the key."},
            },
            "required": ["key", "value"]
        }
    })
    async def update_shared_knowledge(self, key: str, value: str) -> ToolResult:
        try:
            shared_knowledge = await self.state_manager.get('shared_knowledge') or {}
            shared_knowledge[key] = value
            await self.state_manager.set('shared_knowledge', shared_knowledge)
            return self.success_response(f"shared_knowledge[{key}] updated.")
        except Exception as e:
            return self.fail_response(f"Error updating shared_knowledge: {str(e)}")
