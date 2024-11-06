import os
import json
import asyncio
import argparse
from agentpress.thread_manager import ThreadManager
from tools.files_tool import FilesTool
from agentpress.state_manager import StateManager
from tools.terminal_tool import TerminalTool

async def run_agent(thread_id: str, max_iterations: int = 5):
    # Initialize managers and tools
    thread_manager = ThreadManager()
    state_manager = StateManager()

    thread_manager.add_tool(FilesTool)
    thread_manager.add_tool(TerminalTool)

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True, help="Path to the repository to analyze")
    parser.add_argument("--problem-file", required=True, help="Path to the problem description JSON file")
    parser.add_argument("--debug", action="store_true", default=False, help="Enable debug mode")
    args = parser.parse_args()

    if args.debug:
        with open("debug.py", "w") as f:
            f.write("# Debug mode enabled")
        print("Debug mode enabled, exiting...")
        return

    # Read the problem statement
    with open(args.problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    async def init():
        # Initialize the thread and add the problem statement
        await thread_manager.add_message(thread_id, {
            "role": "user",
            "content": problem_statement
        })

    async def pre_iteration():
        # Update files state
        files_tool = FilesTool()
        await files_tool._init_workspace_state()

    async def after_iteration():
        # Ask the user for a custom message or use the default
        custom_message = input("Enter a message to send (or press Enter to continue): ")

        message_content = custom_message if custom_message else """ 
Continue!!!
"""
        await thread_manager.add_message(thread_id, {
            "role": "user",
            "content": message_content
        })

    async def finalizer():
        pass

    await init()

    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        await pre_iteration()

        system_message = {
            "role": "system",
            "content": """
You are a highly skilled software engineer tasked with fixing a bug in the codebase. Follow these instructions:

1. Read the problem statement carefully.
2. Analyze the existing code in the workspace.
3. Apply necessary changes to fix the issue.
4. Ensure your changes adhere to best coding practices.
5. Output the diff of your changes in unified diff format.

<available_tools>
[create_file(file_path, file_contents)] - Create new files
[delete_file(file_path)] - Delete existing files
[str_replace(file_path, old_str, new_str)] - Replace specific text in files
[execute_command(command)] - Execute terminal commands
</available_tools>

Do not include any explanations or comments in your output. Only output the diff.

Think deeply and step by step.
            """
        }

        # Get the current workspace state
        state = await state_manager.export_store()

        state_message = {
            "role": "user",
            "content": f"""
Problem Statement:
{problem_statement}

Current Codebase:
<current_workspace_state>
{json.dumps(state, indent=2)}
</current_workspace_state>
            """
        }

        model_name = "anthropic/claude-3-5-sonnet-latest"

        response = await thread_manager.run_thread(
            thread_id=thread_id,
            system_message=system_message,
            model_name=model_name,
            temperature=0.1,
            max_tokens=4096,
            tool_choice="auto",
            additional_message=state_message,
            execute_tools_async=True,
            use_tools=True,
            execute_model_tool_calls=True
        )

        print(response)

        await after_iteration()

    await finalizer()

if __name__ == "__main__":
    async def main():
        thread_manager = ThreadManager()
        thread_id = await thread_manager.create_thread()

        await run_agent(thread_id)

    asyncio.run(main())
