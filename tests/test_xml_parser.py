import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agentpress.xml_tool_parser import XMLToolParser
from agent.agentpress.tool_registry import ToolRegistry
from dataclasses import dataclass
from agent.tools.repo_tool import RepositoryTools

@dataclass
class XMLSchema:
    xml_schema: any
    json_schema: any = None

@dataclass
class XMLMapping:
    node_type: str
    path: str
    param_name: str

def create_test_registry():
    registry = ToolRegistry()
    # Create a simple schema for testing view command
    schema = XMLSchema(xml_schema={
        "mappings": [
            XMLMapping("attribute", "path", "path"),
            XMLMapping("attribute", "depth", "depth")
        ]
    })
    # Register view tool
    registry.xml_tools["view"] = {
        "method": "view",
        "schema": schema
    }
    return registry

async def main():
    # Test XML string with view command
    test_xml = """Let me examine the repository structure.
    <view path="/testbed" depth="3" />
    I'll analyze the contents."""

    # Test case 2 - content with OBSERVE tags and view command
    test_xml_2 = """I'll help you investigate and implement the necessary changes to address the issue with overriding get_FOO_display() in Django 2.2+.

<OBSERVE> 1. The issue is about the inability to override get_FIELD_display() method in Django 2.2+ 2. The workspace is currently empty, so I need to first examine the repository structure 3. The example shows a model with a CharField that has choices and attempts to override get_foo_bar_display() </OBSERVE> <REASON> First, I should view the repository structure to locate relevant files and understand the codebase organization. </REASON> <ACTION> <view path="/testbed" depth="3" /> </ACTION>"""

    # Create mock response objects for both tests
    @dataclass
    class Choice:
        message: dict

    @dataclass
    class Response:
        choices: list

    mock_responses = [
        Response(choices=[Choice(message={"content": test_xml})]),
        Response(choices=[Choice(message={"content": test_xml_2})])
    ]

    # Initialize parser with test registry
    parser = XMLToolParser(create_test_registry())

    # Test both responses
    for i, response in enumerate(mock_responses, 1):
        print(f"\nTesting Response {i}:")
        print("=" * 50)
        result = await parser.parse_response(response)
        print(f"Role: {result['role']}")
        print(f"Content: {result['content']}")
        if 'tool_calls' in result:
            print("\nTool Calls:")
            for tool in result['tool_calls']:
                print(f"Tool ID: {tool['id']}")
                print(f"Function Name: {tool['function']['name']}")
                print(f"Arguments: {tool['function']['arguments']}")

if __name__ == "__main__":
    asyncio.run(main())