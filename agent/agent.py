import json
import asyncio
import argparse
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from tools.files_tool import FilesTool
from agentpress.state_manager import StateManager
from tools.terminal_tool import TerminalTool

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 7, model_name: str = "sonnet"):
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

    await thread_manager.add_message(thread_id, {
            "role": "user",
            "content": f"""
<uploaded_files>
/testbed/
</uploaded_files>
I've uploaded a python code repository in the directory /testbed. Consider the following PR description:
Consider the following PR description:
<pr_description>
{problem_statement}
</pr_description>

Can you help me implement the necessary changes to the repository so that the requirements specified in the <pr_description> are met?
I've already taken care of all changes to any of the test files described in the <pr_description>. This means you DON'T have to modify the testing logic or any of the tests in any way!

Your task is to make the minimal changes to non-tests files in the current directory to ensure the <pr_description> is satisfied.

Follow these steps to resolve the issue:
1. As a first step, it might be a good idea to explore the repo to familiarize yourself with its structure.
2. Create a script to reproduce the error and execute it with `python <filename.py>` using the BashTool, to confirm the error
3. Edit the sourcecode of the repo to resolve the issue
4. Rerun your reproduce script and confirm that the error is fixed!
5. Think about edgecases and make sure your fix handles them as well.

Please avoid command that can produce lengthy output. Always use absolute paths.

You're working autonomously from now on. You should start by explore the repo now.
            """
    })
#     await thread_manager.add_message(thread_id, {
#             "role": "user",
#             "content": f"""
# Problem Statement:
# {problem_statement}
#             """
#     })

    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        if model_name == "sonnet":
            model_name_full = "anthropic/claude-3-5-sonnet-latest"
        elif model_name == "haiku":
            model_name_full = "anthropic/claude-3-5-haiku-latest"
        elif model_name == "deepseek":
            model_name_full = "deepseek/deepseek-chat"
        elif model_name == "gpt-4o":
            model_name_full = "gpt-4o"
        else:
            model_name_full = "anthropic/claude-3-5-sonnet-latest"  # default

        response = await thread_manager.run_thread(
            thread_id=thread_id,
            # system_message=system_message,
            model_name=model_name_full,
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

        # await after_iteration()

    print(f"Agent completed after {iteration} iterations")

if __name__ == "__main__":
    async def main():
        parser = argparse.ArgumentParser()
        parser.add_argument("--problem-file", required=True, help="Path to the problem description JSON file")
        parser.add_argument("--container-name", required=True, help="Docker container name")
        parser.add_argument("--threads-dir", required=True, help="Directory to store thread outputs")
        parser.add_argument("--debug", action="store_true", default=False, help="Enable debug mode")
        parser.add_argument("--max-iterations", type=int, default=7, help="Maximum number of iterations")
        parser.add_argument("--model-name", choices=["sonnet", "haiku", "deepseek", "gpt-4o"], default="sonnet",
                            help="Model name to use (choices: sonnet, haiku, deepseek)")
        args = parser.parse_args()

        thread_manager = ThreadManager(threads_dir=args.threads_dir)
        thread_id = await thread_manager.create_thread()
        await run_agent(
            thread_id,
            args.container_name,
            args.problem_file,
            args.threads_dir,
            max_iterations=args.max_iterations,
            model_name=args.model_name
        )

    asyncio.run(main())
