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
        
#         Your current workspace state (similar to VS Code):
# <current_state>
# {workspace}
# </current_state>

# This workspace shows your current context:
# - EXPLORER: Shows the repository structure
# - OPEN EDITORS: Files you're currently viewing/editing
# - TERMINAL SESSION: Recent command inputs and their outputs

        instructions = f"""
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

CRITICAL REQUIREMENTS FOR ALL SCRIPTS:
1. VERBOSE LOGGING IS MANDATORY:
   - EVERY script MUST include detailed logging
   - Print step-by-step execution progress
   - Show input values and parameters
   - Display intermediate results
   - Report all operations and their outcomes
   - Include debugging information
   - NEVER return empty output
   - Use logging format:
     ```
     [STEP] Description of current step
     [INPUT] Show input values
     [DEBUG] Show intermediate values
     [RESULT] Show operation result
     [STATUS] Success/Failure indication
     ```

2. ERROR HANDLING:
   - ALL errors must be caught and logged
   - Show full error traces
   - Explain error context
   - Provide debugging hints

3. VALIDATION:
   - Verify all inputs
   - Check all outputs
   - Validate results
   - Report validation status

IMPORTANT: 
- All test files have been properly configured - DO NOT modify any test files
- Focus only on minimal changes to source files
- NEVER accept scripts that return empty output
- ALL scripts MUST include verbose logging

REQUIRED WORKFLOW:
1. EXPLORE AND UNDERSTAND:
   - Use 'view' to explore the entire repository
   - Search for and identify ALL relevant test files:
     * Look in /tests/ directories
     * Find test files matching source files
     * Study test patterns and methodologies
   - Map out all relevant source files
   - Understand the codebase structure
   - Document your findings

2. REPRODUCE THE ERROR:
   - Create a minimal script with VERBOSE logging to reproduce the issue
   - Run it to verify the exact error
   - Compare with issue description
   - Verify against existing test patterns
   - Document the reproduction

3. ANALYZE DEEPLY:
   - Study the error cause
   - Map affected code paths
   - Consider edge cases
   - Document assumptions
   - Plan minimal changes

4. IMPLEMENT CAREFULLY:
   - Make minimal source changes
   - Use ONLY replace_string
   - Follow code style
   - Document changes

5. VERIFY THOROUGHLY:
   - Create verification scripts with VERBOSE logging
   - Rerun reproduction script
   - Confirm error is fixed
   - Test edge cases
   - Document all results

6. FINAL REVIEW:
   - Review entire solution
   - Verify minimal changes
   - Check all edge cases
   - Confirm issue resolution
   - Document verification

NEVER submit until ALL steps are complete and verified!
NEVER accept scripts that return empty output!

Start by exploring the repository to understand its structure.
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