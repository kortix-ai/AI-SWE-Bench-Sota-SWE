import json
import asyncio
import argparse
import os
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
import uuid

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 10, model_name: str = "sonnet"):
    thread_manager = ThreadManager(threads_dir=threads_dir)
    state_file = os.path.join(threads_dir, thread_id, 'state.json')
    state_manager = StateManager(store_file=state_file)

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

    from tools.repo_tool import RepositoryTools
    thread_manager.add_tool(RepositoryTools, container_name=container_name, state_file=state_file)

    system_message = {
            "role": "system",
            "content": f"""You are an expert at analyzing and fixing issues python open source repositories. Your purpose is to understand PR requirements and implement precise, minimal changes that solve the described issues while making minial changes. Follow suggested TASKS to resolve the issue."""
    }

    await thread_manager.add_message(thread_id, {
            "role": "user",
            "content": f"""
<uploaded_files>
/testbed/
</uploaded_files>
I've uploaded a python code repository in the directory /testbed. Consider the following PR description :
I've uploaded a python code repository in /testbed. Let's systematically analyze and fix the issue described in this PR:

<pr_description>
{problem_statement}
</pr_description>

Can you help me implement the necessary changes to the repository so that the requirements specified in the <pr_description> are met?
I've already taken care of all changes to any of the test files described in the <pr_description>. This means you DON'T have to modify the testing logic or any of the tests in any way!

Your task is to make the minimal changes to non-tests files in the current directory to ensure the <pr_description> is satisfied.

PHASE 1: ANALYSIS
1. First, analyze the PR description to identify:
   - Core issue/bug description
   - Expected behavior
   - Current behavior

2. Explore the codebase structure:
   - Map out relevant modules and their relationships
   - Identify primary affected files
   - Document any related subsystems
   - Note any potential ripple effects
   - All current test cases of the repository

3. Create a reproduction case:
   - Write a minimal script to reproduce the issue
   - Verify the exact error conditions
   - Document all edge cases mentioned in the PR
   - Test related functionality that might be affected

PHASE 2: SOLUTION DESIGN
1. Propose solution strategy:
   - List all possible approaches
   - Analyze pros/cons of each approach
   - Consider backwards compatibility
   - Consider edge cases and error conditions

2. Review impacted areas:
   - Document all files that need changes
   - Consider interface changes
   - Look for similar patterns in codebase that might need similar fixes
   - Check for dependency impacts

PHASE 3: IMPLEMENTATION
1. Make the minimal required changes:
   - Follow existing code style
   - Keep changes minimal but working and complete

2. Comprehensive Testing:
   - Run the reproduction case
   - Execute specific test cases
   - Run full existing test suite
   - Verify edge cases
   - Check for regressions

PHASE 4: VALIDATION
1. Verify the fix:
   - Confirm original issue is resolved
   - Check all test cases pass
   - Verify no new issues introduced
   - Validate edge cases
   - Confirm backwards compatibility

2. Documentation:
   - Document any assumptions
   - Note any limitations
   - Explain the fix approach
   - List any related issues

Think step by step and be thorough in your analysis. Document your thought process using <thoughts> tags. For each change:
- Explain why it's needed
- Show how it fixes the issue
- Consider potential impacts

Remember:
- Don't modify test files
- Make minimal but complete changes
- Consider all edge cases
- Maintain existing code patterns

You're working autonomously from now on. Your thinking should be thorough, step by step, .
            """,

        "tool_calls": [
            {
                "id": str(uuid.uuid4()),
                "type": "function",
                "function": {
                    "name": "view",
                    "arguments": json.dumps({"paths": ["/testbed"], "depth": 1})
                }
            },
        ]
    })
    
    # await thread_manager.add_message(thread_id, {
    #     "role": "assistant",
    #     "content": """<thoughts>\nLet's start by exploring the repository to find relevant files:\n</thoughts>""",
    #     "tool_calls": [
    #         {
    #             "id": str(uuid.uuid4()),
    #             "type": "function",
    #             "function": {
    #                 "name": "view",
    #                 "arguments": json.dumps({"paths": ["/testbed"], "depth": 1})
    #             }
    #         },
    #     ]
    # })

    # await thread_manager.process_last_assistant_message(thread_id)

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
            max_tokens=4096,
            tool_choice="auto",
            execute_tools_async=True,
            use_tools=True,
            execute_model_tool_calls=True
        )

        print(f"Iteration {iteration}/{max_iterations}:")

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
