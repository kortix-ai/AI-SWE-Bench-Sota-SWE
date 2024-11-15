import json
import asyncio
import argparse
import os
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
import uuid
from prompts import system_prompt, continue_instructions  # Fixed import

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 10, model_name: str = "sonnet"):
    thread_manager = ThreadManager(threads_dir=threads_dir)
    state_file = os.path.join(threads_dir, thread_id, 'state.json')
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state_manager = StateManager(store_file=state_file)

    async def after_iteration():
        # Get all previous messages
        messages = await thread_manager.list_messages(thread_id)
        
        # Replace any previous continue instructions with shortened tag
        for i, message in enumerate(messages):
            if message['role'] == 'user' and message['content'] == continue_instructions:
                await thread_manager.modify_message(thread_id, i, {
                    "role": "user",
                    "content": "<continue_instructions></continue_instructions>"
                })
        
        # Add new continue instructions message
        await thread_manager.add_message(thread_id, {
            "role": "user",
            "content": continue_instructions
        })

    with open(problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    from tools.repo_tool import RepositoryTools
    thread_manager.add_tool(RepositoryTools, container_name=container_name, state_file=state_file)

    # Format the system prompt with the problem statement
    system = system_prompt.format(problem_statement=problem_statement)
    
    system_message = {
        "role": "system",
        "content": system
    }

    await thread_manager.add_message(thread_id, {
        "role": "user",
        "content": f"""
<uploaded_files>
/testbed/
</uploaded_files>
I've uploaded a python code repository in the directory /testbed. Consider the following issue description :
<issue_description>
{problem_statement}
</issue_description>

IMPLEMENT the necessary changes to the repository so that the requirements specified in the <issue_description> are met.

Your task is to make the minimal changes to non-tests files in the current directory to ensure the <issue_description> is satisfied & the issue is resolved.

Follow these steps to resolve the issue:
1. As a first step, it might be a good idea to explore the repo to familiarize yourself with its structure.
2. View files to have a whole understanding of the codebase. When you found the issue, do not stop exploring but continue to check related files to grasp the codebase context fully before any implementation. 
3. Create a script to reproduce the error and execute it with `python <filename.py>`, to confirm the error. 
4. Edit the sourcecode of the repo to resolve the issue
5. Rerun your reproduce script and related existing tests scripts to confirm that the error is fixed and the code base is maintaining it functionalities !
6. Run a pull request test script, think about edgecases and make sure your fix handles them as well.

You're working autonomously from now on. Your thinking should be thorough, step by step.
"""
    })

    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        model_mapping = {
            "sonnet": "anthropic/claude-3-5-sonnet-latest",
            "haiku": "anthropic/claude-3-5-haiku-latest",
            "deepseek": "deepseek/deepseek-chat",
            "gpt-4o": "gpt-4o",
            "qwen": "openrouter/qwen/qwen-2.5-coder-32b-instruct",
        }
        model_name_full = model_mapping.get(model_name, "anthropic/claude-3-5-sonnet-latest")  # default

        response = await thread_manager.run_thread(
            thread_id=thread_id,
            system_message=system_message,
            model_name=model_name_full,
            temperature=0.0,
            max_tokens=8192,
            tool_choice="auto",
            execute_tools_async=True,
            use_tools=True,
            execute_model_tool_calls=True
        )

        print(f"Iteration {iteration}/{max_iterations}:")

        # await after_iteration()

        # Check for 'submit' tool call in the assistant's last message
        assistant_messages = await thread_manager.list_messages(thread_id, only_latest_assistant=True)
        if assistant_messages:
            last_assistant = assistant_messages[0]
            tool_calls = last_assistant.get('tool_calls', [])
            for tool_call in tool_calls:
                if tool_call['function']['name'] == 'submit':
                    print("Task completed via submit tool, stopping...")
                    return

    print(f"Agent completed after {iteration} iterations")

if __name__ == "__main__":
    async def main():
        parser = argparse.ArgumentParser()
        parser.add_argument("--problem-file", required=True, help="Path to the problem description JSON file")
        parser.add_argument("--container-name", required=True, help="Docker container name")
        parser.add_argument("--threads-dir", required=True, help="Directory to store thread outputs")
        parser.add_argument("--debug", action="store_true", default=False, help="Enable debug mode")
        parser.add_argument("--max-iterations", type=int, default=10, help="Maximum number of iterations")
        parser.add_argument("--model-name", choices=["sonnet", "haiku", "deepseek", "gpt-4o", "qwen"], default="sonnet",
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