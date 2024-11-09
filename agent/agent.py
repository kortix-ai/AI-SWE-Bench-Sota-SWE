import json
import asyncio
import argparse
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from tools.files_tool import FilesTool
from agentpress.state_manager import StateManager
from tools.terminal_tool import TerminalTool

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 3):
    thread_manager = ThreadManager(threads_dir=threads_dir)
    state_manager = StateManager(store_file="state.json")

    async def after_iteration():

        message_content = """ 
        Run test to check if the bug is fixed, if all tests pass, output "FINISHED" without any other text.
        """
        await thread_manager.add_message(thread_id, {
            "role": "user", 
            "content": message_content
        })

    with open(problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    thread_manager.add_tool(FilesTool, container_name=container_name)
    thread_manager.add_tool(TerminalTool, container_name=container_name)

    system_message = {
            "role": "system",
            "content": """
You are a highly skilled software engineer tasked with fixing a bug in a large codebase. Follow these instructions:

1. Read the problem statement carefully.
2. Analyze the existing code in the workspace by executing command (like ls, cat, ... ).
3. Apply necessary changes to fix the issue.

<available_tools>
[create_file(file_path, file_contents)] - Create new files
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

        # model_name = "anthropic/claude-3-5-sonnet-latest"
        model_name = "anthropic/claude-3-5-haiku-latest"

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
        # print(response)

        if "FINISHED" in response:
            print("Bug fixed, stopping...")
            break

        await after_iteration()

    print(f"Agent completed after {iteration} iterations")

if __name__ == "__main__":
    async def main():
        parser = argparse.ArgumentParser()
        parser.add_argument("--problem-file", required=True, help="Path to the problem description JSON file")
        parser.add_argument("--container-name", required=True, help="Docker container name")
        parser.add_argument("--threads-dir", required=True, help="Directory to store thread outputs")
        parser.add_argument("--debug", action="store_true", default=False, help="Enable debug mode")
        args = parser.parse_args()

        thread_manager = ThreadManager(threads_dir=args.threads_dir)
        thread_id = await thread_manager.create_thread()
        await run_agent(thread_id, args.container_name, args.problem_file, args.threads_dir)

    asyncio.run(main())
