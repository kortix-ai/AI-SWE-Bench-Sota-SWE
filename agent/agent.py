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
        
        # Remove any previous continue instructions
        for i, message in enumerate(messages):
            if message['role'] == 'user' and continue_instructions in message['content']:
                await thread_manager.remove_message(thread_id, i)
        
        workspace = await state_manager.get("workspace")
        
        instructions = f"""
<current_state>
{workspace}
</current_state>

Your current workspace state is shown below.
Your current workspace state (similar to VS Code):

<current_state>
{workspace}
</current_state>

This workspace shows your current context:
- EXPLORER: Shows the repository structure
- OPEN EDITORS: Files you're currently viewing/editing
- TERMINAL SESSION: Recent command outputs and their status

{continue_instructions}
"""
        await thread_manager.add_message(thread_id, {
            "role": "user",
            "content": instructions
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
        "content": system + continue_instructions
    }

    await thread_manager.add_message(thread_id, {
        "role": "user", 
        "content": f"""
YOUR GOAL IS SOLVING THE ISSUE.

The python code repository is uploaded in the directory /testbed. 
<current_repository>
/testbed/
</current_repository>

The issue description:
<issue_description>
{problem_statement}
</issue_description>
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
            execute_tools_async=False,
            use_tools=True,
            execute_model_tool_calls=True
        )

        print(f"Iteration {iteration}/{max_iterations}:")

        await after_iteration()

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