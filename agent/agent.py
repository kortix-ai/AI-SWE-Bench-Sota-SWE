import os
import json
import asyncio
import argparse
import subprocess
from agentpress.thread_manager import ThreadManager
from tools.files_tool import FilesTool
from agentpress.state_manager import StateManager
from tools.terminal_tool import TerminalTool

async def run_agent(thread_id: str, max_iterations: int = 7):
    thread_manager = ThreadManager(threads_dir="/tmp/agentpress/threads")
    state_manager = StateManager(store_file="/tmp/agentpress/state.json")

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

    repo_path = os.path.abspath(args.repo_path)
    print(f"Using repository path: {repo_path}")
    await state_manager.set("workspace_path", repo_path)
    state = await state_manager.export_store()
    print(f"Current state: {state}")

    with open(args.problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    thread_manager.add_tool(FilesTool, repo_path=repo_path)
    thread_manager.add_tool(TerminalTool, repo_path=repo_path)

    system_message = {
            "role": "system",
            "content": """
You are a highly skilled software engineer tasked with fixing a bug in a large codebase. Follow these instructions:

1. Read the problem statement carefully.
2. Analyze the existing code in the workspace by executing command (like ls, cat, ... ).
3. Apply necessary changes to fix the issue.
4. Run test to check if the bug is fixed, if all tests pass, output only "FINISHED".
5. You do not have to write any test code as I will cover that.

<available_tools>
[create_file(file_path, file_contents)] - Create new files
[delete_file(file_path)] - Delete existing files
[str_replace(file_path, old_str, new_str)] - Replace specific text in files
[execute_command(command)] - Execute terminal commands
</available_tools>

ALWAYS RESPOND WITH MULTIPLE SIMULTANEOUS ACTIONS:
<thoughts>
[Provide a concise overview of your planned changes and implementations]
</thoughts>

<actions>
[Include multiple tool calls]
</actions>

Think deeply and step by step.
            """
        }

    await thread_manager.add_message(thread_id, {
            "role": "user",
            "content": f"""
Problem Statement:
{problem_statement}

            """
    })

    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        model_name = "anthropic/claude-3-5-sonnet-latest"

        response = await thread_manager.run_thread(
            thread_id=thread_id,
            system_message=system_message,
            model_name=model_name,
            temperature=0.1,
            max_tokens=4096,
            tool_choice="auto",
            execute_tools_async=True,
            use_tools=True,
            execute_model_tool_calls=True
        )

        print(f"Iteration {iteration}/{max_iterations}:")
        print(response)

        if response == "FINISHED":
            print("Bug fixed, stopping...")
            break

    print(f"Agent completed after {iteration} iterations")

if __name__ == "__main__":
    async def main():
        thread_manager = ThreadManager(threads_dir="/tmp/agentpress/threads")
        thread_id = await thread_manager.create_thread()
        await run_agent(thread_id)

    asyncio.run(main())
