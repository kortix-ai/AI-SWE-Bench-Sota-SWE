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

IMPLEMENT the necessary changes to the repository so that the requirements specified in the <issue_description> are met and the issue is resolved.

Your task is to make the minimal changes to non-test files in the current directory to ensure the <issue_description> is satisfied & the issue is resolved.

TOOL USAGE GUIDELINES:
1. EFFICIENT EXECUTION:
   - Combine multiple tool calls in single response
   - Chain related operations together
   - Examples of efficient patterns:

   a) Making multiple changes:
      <actions>
      Tool calls:
      1. replace_string(file1, old1, new1)
      2. replace_string(file1, old2, new2)
      3. create_and_run(test_path, test_content, "python test.py")
      </actions>

   b) Analyzing multiple files:
      <actions>
      Tool calls:
      1. view(paths=["/path1", "/path2", "/path3"])
      </actions>

   c) Running multiple tests:
      <actions>
      Tool calls:
      1. create_and_run(test1_path, test1_content, "python test1.py")
      2. create_and_run(test2_path, test2_content, "python test2.py")
      </actions>

2. TOOL SELECTION:
   - Use 'view' for file exploration
   - Use 'create_and_run' for testing
   - Use 'replace_string' for code changes
   - Use 'bash' only when necessary

CRITICAL: Follow these steps and ALWAYS output your analysis using <observations>, <thoughts>, and <actions> tags:

1. EXPLORE AND UNDERSTAND:
   - Use 'view' to explore the repo structure
   - Search for and identify ALL relevant test files:
     * Look in /tests/ directories
     * Find test files matching source files you might modify
     * Identify related test suites and helpers
   - View ALL related files to understand the codebase context
   - Take time to understand the complete problem space
   - Think through potential edge cases
   - Consider failure modes
   - Document all assumptions

2. ANALYZE EXISTING TESTS:
   - Study ALL identified test files thoroughly
   - Understand existing test patterns and methodologies
   - Document current test coverage and edge cases
   - Analyze how similar functionality is tested
   - Take time to understand test approaches
   - Consider test variations needed

3. CREATE COMPREHENSIVE TESTS:
   - Use 'create_and_run' to develop AT LEAST 3 different reproduction scripts:
     * Basic functionality tests
     * Edge case tests
     * Complex scenario tests
   - Each variation must:
     * Test different aspects thoroughly
     * Cover potential edge cases
     * Verify error conditions
     * Check backward compatibility
   - Document ALL test results
   - Analyze results carefully

4. IMPLEMENT AND VERIFY:
   - Use 'replace_string' for ALL source code modifications
   - Run ALL reproduction variations
   - Verify ALL test cases pass
   - Check backward compatibility
   - Document ALL results
   - Take time to analyze changes

5. STEP BACK AND REFLECT:
   - Review the entire solution journey
   - Question all assumptions
   - Re-examine all changes
   - Consider what might be missed
   - Think about edge cases again
   - Review ALL observations chronologically
   - Verify ALL fixes are complete
   - Consider long-term implications

REMEMBER:
- ALWAYS output <observations>, <thoughts>, and <actions>
- Take time to think thoroughly
- Test ALL variations comprehensively
- Document ALL results carefully
- Never rush to submit
- Step back and verify
- Ensure 100% confidence in solution
- Use the correct tool for each task

You're working autonomously. Think deeply and step by step.
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