import json
import asyncio
import argparse
import os
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
import agentops

agentops.init(os.environ['AGENTOPS_API_KEY'])


system_prompt = """You are an autonomous expert software engineer focused on implementing precise, high-quality changes to solve specific issues.

<IMPORTANT>
- Before modifying any files, thoroughly analyze the problem by observing and reasoning about the issue.
- Use the following tags to structure your thought process and actions:
  - <OBSERVE>: Note observations about the codebase, files, or errors.
  - <REASON>: Analyze the issue, consider causes, evaluate potential solutions, and assess how changes might affect other parts of the codebase. Always consider code interdependencies.
  - <FIX>: Propose multiple solutions with short code update snippets (```file_path\n{{edit1}}\n\n{{edit2}}...), prioritize changes that align with existing code patterns and standards. Analyze the quality and simplicity of each proposed solution, and select the one that is most effective and compliant with standards. With that choice, reflect to the original file to check if any other parts should be updated accordingly.
  - <PLAN>: Outline your intended approach before implementing changes.
  - <ACTION>: Document the actions you take, such as modifying files or running commands.
  - <CHECK>: Verify and analyze the results after EVERY tool use. Always examine the output for errors, unexpected behavior, or important information.
  - <REVIEW>: Thoroughly inspect the modified code to assess whether it meets all the requirements and determine if further updates are necessary. Specifically:
    - Inspect the code thoroughly for quality and correctness
    - Identify any other parts of the code that might be affected by your changes
    - Update related functions or modules to ensure consistency
    - Verify error prevention measures:
      • Input validation - Ensure all inputs are properly validated
      • Exception handling - Add appropriate try/except blocks
      • Graceful degradation - System should handle failures elegantly
      • Fail-safe operations - Default to safe states on error
      • Data validation - Verify data integrity at all stages
      • Type checking - Ensure proper type safety
  - <CRITICAL>: Evaluate the overall quality of your work, ensuring concise changes with no regressions.
- Always use <CHECK> after receiving tool results to analyze the output and determine next steps.
- After making changes, use <REVIEW> to:
  - Inspect the code thoroughly.
  - Identify any other parts of the code that might be affected by your changes.
  - Update related functions or modules to ensure consistency and correctness.
- Always think about how changes in one area might impact other parts of the system.
- Aim for solutions that maintain alignment with existing code patterns and adhere to relevant standards.
- Maintain a checklist of tasks to track your progress, marking each as completed when done.
- Ensure that your changes do not affect existing test cases. **Do not modify any existing test files; you can read them.**
- Only after ensuring existing tests pass, create your own scripts (e.g., `reproduce_error.py`, `edge_cases.py`) to test if the fix is working and to cover edge cases.
- Think deeply about edge cases and how your changes might impact other parts of the system.
- Always ensure that any changes comply with relevant standards and do not violate existing specifications.
- You work AUTONOMOUSLY; never ask the user for additional information. ALWAYS use at least one tool.
- Avoid using pytest.
</IMPORTANT>
"""

user_prompt = """
I've uploaded a Python code repository in the directory `/testbed/`. Consider the following PR description:

<pr_description>
{problem_statement}
</pr_description>

Can you help me implement the necessary changes to the repository so that the requirements specified in the <pr_description> are met?

**Important Notes:**

- Your task is to make changes to the non-test files in the `/testbed` directory to ensure the <pr_description> is satisfied.
- Analyze the issue thoroughly before making any changes.
- After EVERY tool use, use <CHECK> to analyze the output and determine next steps.
- Ensure that your changes do not affect existing test cases. **Do not modify any existing test files; you can read them.**
- Only after ensuring existing tests pass, create your own scripts (e.g., `reproduce_error.py`, `edge_cases.py`) to test if the fix is working and to handle edge cases.
- After implementing changes, use <REVIEW> to:
  - Inspect the modified code.
  - Determine if any additional updates are necessary.
  - Search for and address similar issues in related code sections.
  - Ensure that all changes are consistent throughout the codebase.
- Use the following tags to structure your work: <OBSERVE>, <REASON>, <FIX>, <PLAN>, <ACTION>, <CHECK>, <REVIEW>, <CRITICAL>.

**Suggested Steps:**

1. Explore `/testbed` and find files related to the issue.
2. Expand the search scope to related files; you may view multiple files at once.
3. Analyze the PR description to understand the issue in detail.
4. Examine related files, understand how they are written, and identify the root cause.
5. Use <FIX> to consider multiple possible solutions, propose solutions, and pick the best one.
6. Implement the fix directly, updating related parts of the code accordingly.
7. Only after ensuring existing tests pass, create your own scripts (e.g., `reproduce_error.py`, `edge_cases.py`) to test if the fix is working and to handle edge cases.
8. Use <REVIEW> to thoroughly inspect the modified code:
   - Determine if any additional updates are necessary.
   - Search for and address similar issues in related code sections.
   - Ensure that all changes are consistent throughout the codebase.
9. Use <CRITICAL> to evaluate your changes for effectiveness, handling of edge cases, and absence of regressions.
10. Report your findings or submit the fix.

**Current Workspace State:**
<workspace_state>
{workspace_state}
</workspace_state>

Remember to use the tags appropriately to structure your response and thought process.
"""

continuation_system_prompt = """You are continuing your previous work as an autonomous expert software engineer. Focus on analyzing, evaluating, and continuing the tasks based on your current progress and the workspace state.

<IMPORTANT>
- Build upon your previous analysis and actions.
- Review the current workspace state and your checklist of tasks with a critical eye.
- Always take things with a grain of salt; question your assumptions and verify your conclusions.
- Recheck everything: double-check your previous steps and ensure that all files are fully updated and consistent.
- Continue implementing precise, high-quality changes to solve the specific issue described.
- Use the following tags to structure your thought process and actions:
  - <OBSERVE>: Note new observations about the codebase, files, or errors.
  - <REASON>: Critically analyze the current situation, consider causes, evaluate potential solutions, and assess the impact of changes on other code parts. Always check for code interdependencies.
  - <FIX>: Propose additional solutions if necessary, prioritizing effective changes. A fix may involve changes to one or multiple files.
  - <PLAN>: Update your approach before implementing further changes.
  - <ACTION>: Document additional actions you take.
  - <CHECK>: Verify and analyze the results after EVERY tool use. Always examine the output for errors, unexpected behavior, or important information.
  - <REVIEW>: Thoroughly inspect the modified code to assess whether it meets all the requirements and determine if further updates are necessary. Specifically:
    - Search for other parts of the code that might be affected by your changes.
    - Update related functions/modules for consistency.
    - Verify error prevention measures:
      • Input validation - Ensure all inputs are properly validated.
      • Exception handling - Add appropriate try/except blocks.
      • Graceful degradation - System should handle failures elegantly.
      • Fail-safe operations - Default to safe states on error.
      • Data validation - Verify data integrity at all stages.
      • Type checking - Ensure proper type safety.
  - <CRITICAL>: Evaluate the overall quality of your work with a critical mindset, ensuring concise changes with no regressions.
- Always use <CHECK> after receiving tool results to analyze the output and determine next steps.
- After making changes, use <REVIEW> to inspect the code and decide if any additional updates are necessary to fully meet the requirements.
- Maintain your checklist of tasks, marking each as completed when done.
- Ensure that your changes do not affect existing test cases. **Do not modify any existing test files; you can read them.**
- Only after ensuring existing tests pass, create your own scripts (e.g., `reproduce_error.py`, `edge_cases.py`) to test (e.g python reproduce_error.py) if the fix is working and to cover edge cases.
- Think deeply about edge cases and how your changes might impact other parts of the system.
- Always ensure that any changes comply with relevant standards and do not violate existing specifications.
- Be skeptical of your own work; revisit your changes to confirm their correctness.
- You work AUTONOMOUSLY; never ask the user for additional information. ALWAYS use at least one tool.
- If it doesn't work after multiple attempts, you can use the reset feature of EditTool to restore files for a fresh start, then examine the files again and propose a better, elegant solution.
- If you modified a non-test file, please use 'view' to check the file again, and make sure to update relevant parts that might be affected by your changes
</IMPORTANT>
"""

continuation_prompt = """
This is a continuation of the previous task. You are working on implementing the necessary changes to the repository to meet the PR description requirements.

<pr_description>
{problem_statement}
</pr_description>

**Please proceed with the following steps, using the tags to structure your work:**

1. Review the current workspace state and note your accomplishments so far.
2. Re-evaluate the issue in light of the work done and adjust your approach if necessary.
3. Update your plan based on your observations and reasoning.
4. Continue implementing the fix, ensuring compliance with standards, high quality, and no impact on existing functionality.
5. Use <REVIEW> to thoroughly inspect the modified code:
   - Determine if any additional updates are necessary.
   - Search for and address similar issues in related code sections.
   - Ensure that all changes are consistent throughout the codebase.
6. Only after ensuring existing tests pass, create your own scripts (e.g., `reproduce_error.py`, `edge_cases.py`) to confirm that the error is fixed and handle edge cases.
7. Use <CRITICAL> to evaluate whether your solution adheres to high-quality standards, handles all edge cases, and introduces no regressions.

**Current Workspace State:**
<workspace_state>
{workspace_state}
</workspace_state>

Remember to build upon your previous work rather than starting over. Use the tags (<OBSERVE>, <REASON>, <FIX>, <PLAN>, <ACTION>, <CHECK>, <REVIEW>, <CRITICAL>) to structure your thought process and responses.
"""

#------------------------------------------------------------

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 10, reset_interval: int = 8, model_name: str = "sonnet"):
    # Start agentops session at the beginning of run_agent
    agentops_session = agentops.start_session()
    
    thread_manager = ThreadManager(threads_dir=threads_dir)
    state_file = os.path.join(threads_dir, thread_id, 'state.json')
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state_manager = StateManager(store_file=state_file)

    workspace_state = {
        "checklist_of_tasks": """Status of tasks:
1. [ ] Explore `/testbed` and find relevant files.
2. [ ] Analyze PR description and issue details.
3. [ ] Examine related files and understand code patterns, relevant functions.
4. [ ] Analyze root cause with related files.
5. [ ] Consider multiple possible solutions, propose solutions, and pick the best one.
6. [ ] Implement the fix directly, updating related parts of the code accordingly.
7. [ ] Create 'reproduce_error.py' and 'edge_cases.py' to test if the fix is working and to handle edge cases.
8. [ ] Review modified files and identify any dependent code that needs updates.
9. [ ] Use <REVIEW> to ensure all changes are consistent and correct.
10. [ ] Use <CRITICAL> to evaluate your changes for effectiveness and absence of regressions.
11. [ ] Report findings or submit the fix."""
    }
    await state_manager.set('workspace_state', workspace_state)

    with open(problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    from tools.repo_tool import RepositoryTools
    thread_manager.add_tool(RepositoryTools, container_name=container_name, state_file=state_file)
    from tools.bash_tool import BashTool
    thread_manager.add_tool(BashTool, container_name=container_name, state_file=state_file)
    from tools.edit_and_run_tool import EditTool
    thread_manager.add_tool(EditTool, container_name=container_name, state_file=state_file)
    from tools.report_tool import ReportTool
    report_tool = ReportTool(state_file=state_file)
    outer_iteration = 0
    total_iterations = 0
    xml_examples = thread_manager.tool_registry.get_xml_examples()
    xml_format = (
        "\n\nSTRICTLY OUTPUT YOUR ACTIONS / TOOL CALLS IN THE FOLLOWING XML FORMAT'S WITHIN THE <ACTION> TAG:\n"
        "<AVAILABLE_XML_TOOLS>\n"
        f"{json.dumps(xml_examples, indent=2)}\n"
        "</AVAILABLE_XML_TOOLS>"
    )

    async def execute_view_commands(thread_manager, thread_id, workspace_state):
        folders = workspace_state.get('open_folders', [])
        if folders:
            folder_view_arguments = {
                "paths": list(set(folders)),
                "depth": 1
            }
            await thread_manager.execute_tool_and_add_message(thread_id, "user", 'view', folder_view_arguments)

        files = workspace_state.get('open_files_in_code_editor', [])
        if files:
            file_view_arguments = {
                "paths": list(set(files)),
            }
            await thread_manager.execute_tool_and_add_message(thread_id, "user", 'view', file_view_arguments)

    while total_iterations < max_iterations:
        outer_iteration += 1
        inner_iteration = 0

        await thread_manager.reset_messages(thread_id)

        workspace_state = await state_manager.get('workspace_state')

        if total_iterations == 0:
            # init
            system_message = {
                "role": "system", 
                "content": system_prompt
            } #+ xml_format
            await thread_manager.add_message(thread_id, system_message)

            await thread_manager.add_message(thread_id, {
                "role": "user",
                "content": user_prompt.format(
                    problem_statement=problem_statement,
                    workspace_state=report_tool.format_workspace_report(workspace_state)
                )
            })
        else:
            # continue
            system_message = {
                "role": "system",
                "content": continuation_system_prompt
            }
            await thread_manager.add_message(thread_id, system_message)

            await thread_manager.add_message(thread_id, {
                "role": "user",
                "content": continuation_prompt.format(
                    problem_statement=problem_statement,
                    workspace_state=report_tool.format_workspace_report(workspace_state)
                )
            })

            await execute_view_commands(thread_manager, thread_id, workspace_state)

            # Execute test commands
            test_commands = workspace_state.get('test_commands', [])
            for cmd in test_commands:
                bash_test_arguments = {
                    "command": cmd
                }
                await thread_manager.execute_tool_and_add_message(thread_id, "user", 'bash_command', bash_test_arguments)

        while inner_iteration < reset_interval and total_iterations < max_iterations:
            inner_iteration += 1
            total_iterations += 1

            model_mapping = {
                "sonnet": "anthropic/claude-3-5-sonnet-latest",
                "haiku": "anthropic/claude-3-5-haiku-latest",
                "deepseek": "deepseek/deepseek-chat",
                "gpt-4o": "gpt-4o",
                "qwen": "openrouter/qwen/qwen-2.5-coder-32b-instruct",
            }
            model_name_full = model_mapping.get(model_name, "anthropic/claude-3-5-sonnet-latest")

            print(f"Iteration {total_iterations}/{max_iterations} (Reset cycle {outer_iteration}, Step {inner_iteration})")

            if inner_iteration == reset_interval:
                thread_manager.add_tool(ReportTool, state_file=state_file)
                await thread_manager.add_message(thread_id, {
                    "role": "user",
                    "content": (
                        "Time's up! Please review your checklist of tasks and indicate which tasks have been completed. "
                        "If you have completed all tasks and are confident that the issue is resolved, please SUBMIT your fix. "
                        "Otherwise, report the current state of the workspace without doing anything else and provide instructions "
                        "for the next iteration using ReportTool."
                    )
                })
                tool_choice = "any"
            else:
                tool_choice = "any"

            response = await thread_manager.run_thread(
                thread_id=thread_id,
                system_message=system_message,
                model_name=model_name_full,
                temperature=0.0,
                max_tokens=8192,
                tool_choice=tool_choice,
                native_tool_calling=True,
                xml_tool_calling=False,
                parallel_tool_execution=False,
                agentops_session=agentops_session,  
            )

            assistant_messages = await thread_manager.list_messages(thread_id, only_latest_assistant=True)
            if assistant_messages:
                last_assistant = assistant_messages[0]
                tool_calls = last_assistant.get('tool_calls', [])
                for tool_call in tool_calls:
                    if tool_call['function']['name'] == 'submit':
                        print("Task completed via submit tool, stopping...")
                        agentops_session.end_session()
                        return

        if total_iterations < max_iterations:
            await thread_manager.add_to_history_only(thread_id, {
                "role": "switch",
                "content": "--- Resetting workspace state ---"
            })

    print(f"Agent completed after {total_iterations} total iterations ({outer_iteration} reset cycles)")

    agentops_session.end_session()

if __name__ == "__main__":
    async def main():
        parser = argparse.ArgumentParser()
        parser.add_argument("--problem-file", required=True, help="Path to the problem description JSON file")
        parser.add_argument("--container-name", required=True, help="Docker container name")
        parser.add_argument("--threads-dir", required=True, help="Directory to store thread outputs")
        parser.add_argument("--debug", action="store_true", default=False, help="Enable debug mode")
        parser.add_argument("--max-iterations", type=int, default=31, help="Maximum number of iterations")
        parser.add_argument("--model-name", choices=["sonnet", "haiku", "deepseek", "gpt-4o", "qwen"], default="sonnet",
                            help="Model name to use")
        parser.add_argument("--reset-interval", type=int, default=10, help="Number of iterations before state reset")
        args = parser.parse_args()

        thread_manager = ThreadManager(threads_dir=args.threads_dir)
        thread_id = await thread_manager.create_thread()
        await run_agent(
            thread_id,
            args.container_name,
            args.problem_file,
            args.threads_dir,
            max_iterations=args.max_iterations,
            reset_interval=args.reset_interval,
            model_name=args.model_name
        )

    asyncio.run(main())
