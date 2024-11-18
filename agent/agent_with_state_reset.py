import json
import asyncio
import argparse
import os
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
import uuid
# from prompts import system_prompt, continue_instructions 
from tools.summary_tool import SummaryTool



system_prompt = """You are an autonomous expert software engineer focused on implementing precise, minimal changes to solve specific issues.

<IMPORTANT>
- Before modifying any files, thoroughly analyze the problem by observing and reasoning about the issue.
- Use the following tags to structure your thought process and actions:
  - <OBSERVE>: To note observations about the codebase, files, or errors.
  - <REASON>: To analyze the issue, consider possible causes, and evaluate potential solutions.
  - <FIX>: To propose multiple fix solutions. 
  - <PLAN>: To outline your intended approach before implementing changes.
  - <ACTION>: To document the actions you take, such as modifying files or running commands.
  - <CHECK>: To verify that your changes work as intended and do not introduce regressions.
  - <CRITICAL>: To evaluate the overall quality of your work and ensure minimal concise changes, no regressions.
- Maintain a checklist of tasks to track your progress, marking each as completed when done.
- Ensure that your changes are minimal and do not affect existing test cases. You cannot run existing test files; you can only read them. Instead, create your own scripts (e.g., `reproduce_error.py`, `edge_cases.py`) to test your changes.
- Think deeply about edge cases and how your changes might impact other parts of the system.
</IMPORTANT>
"""

user_prompt = """
I've uploaded a Python code repository in the directory `/testbed/`. Consider the following PR description:

<pr_description>
{problem_statement}
</pr_description>

Can you help me implement the necessary changes to the repository so that the requirements specified in the <pr_description> are met?

**Important Notes:**

- Your task is to make minimal changes to the non-test files in the `/testbed` directory to ensure the <pr_description> is satisfied.
- Focus on analyzing the issue thoroughly before making any changes.
- Ensure that your changes do not affect existing test cases. You cannot run existing test files; you can only read them. Instead, you can create a `reproduce_error.py` script to test the error and an `edge_cases.py` script to test edge cases.
- Use the following tags to structure your work:
  - <OBSERVE>, <REASON>, <FIX>, <PLAN>, <ACTION>, <CHECK>, <CRITICAL>
- Keep a **checklist of tasks** and track your progress as you complete each step.

**Suggested Steps:**

1. Explore and find files related to the issue.
2. Expand the search scope to related files.
3. Analyze the PR description and understand the issue in detail.
4. Identify the root cause by examining the related files.
5. Check related existing test files.
6. User <FIX> to consider all possible ways to fix the issue without affecting existing test cases.
7. Decide on the minimal solution that can work to pass pull request requirements.
8. Reproduce the error to confirm the issue.
9. Implement the fix, ensuring it does not affect other test cases.
10. Handle edge cases by writing and running additional tests.
11. Use <CRITICAL> to evaluate your changes for minimal concise impact and absence of regressions.
12. Review existing tests to ensure your changes do not introduce regressions. Summarize your findings or submit the fix.

**Current Workspace State:**
<workspace_state>
{workspace_state}
</workspace_state>

Remember to use the tags appropriately to structure your response and thought process.
"""

continuation_prompt = """
This is a continuation of the previous task. You are working on implementing the necessary changes to the repository so that the requirements specified in the PR description are met.

<pr_description>
{problem_statement}
</pr_description>

**Please proceed with the following steps, using the tags to structure your work:**

1. Review the current workspace state and note what has been accomplished so far.
2. Re-evaluate the issue in light of the work done and consider if the approach needs adjustment.
3. Update your plan based on your observations and reasoning.
4. Continue implementing the fix, ensuring minimal changes and no impact on existing tests.
5. Run your reproduction script to confirm that the error is fixed.
6. Handle edge cases by writing and running additional tests.
7. Use <CRITICAL> to evaluate whether your solution adheres to minimal changes, handles all edge cases, and does not introduce regressions.

**Current Workspace State:**
<workspace_state>
{workspace_state}
</workspace_state>

Remember to use the tags (<OBSERVE>, <REASON>, <FIX>, <PLAN>, <ACTION>, <CHECK>, <CRITICAL>) and to update your checklist of tasks as you progress.
"""

#------------------------------------------------------------

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 10, reset_interval: int = 8, model_name: str = "sonnet"):
    thread_manager = ThreadManager(threads_dir=threads_dir)
    state_file = os.path.join(threads_dir, thread_id, 'state.json')
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state_manager = StateManager(store_file=state_file)
    use_xml = False

    workspace_state = {
        "checklist_of_tasks": """Status of tasks:
1. [ ] Explore and find relevant files
2. [ ] Analyze PR description and issue details
3. [ ] Analyze root cause with related files
4. [ ] View existing tests without running them
5. [ ] Consider multiple possible fixes that don't affect existing tests
6. [ ] Choose the best solution which is minimal and precise
7. [ ] Reproduce the error
8. [ ] Implement the fix without affecting other test cases
9. [ ] Handle edge cases
10. [ ] Review existing tests without running them to check for potential regressions
11. [ ] Summarize findings or submit the fix"""
    }
    await state_manager.set('workspace_state', workspace_state)

    with open(problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    from tools.repo_tool import RepositoryTools
    thread_manager.add_tool(RepositoryTools, container_name=container_name, state_file=state_file)

    # from tools.edit_tool import EditTool
    # thread_manager.add_tool(EditTool, container_name=container_name, state_file=state_file)
    from tools.bash_tool import BashTool
    thread_manager.add_tool(BashTool, container_name=container_name, state_file=state_file)
    from tools.edit_and_run_tool import EditTool
    thread_manager.add_tool(EditTool, container_name=container_name, state_file=state_file)
    summary_tool = SummaryTool(state_file=state_file)

    outer_iteration = 0
    total_iterations = 0

    async def execute_view_commands(thread_manager, thread_id, workspace_state):
        folders = workspace_state.get('open_folders', [])
        if folders:
            folder_view_arguments = {
                "paths": list(set(folders)),
                "depth": 1
            }
            await thread_manager.execute_tool_and_add_message(thread_id, 'view', folder_view_arguments)

        files = workspace_state.get('open_files_in_code_editor', [])
        if files:
            file_view_arguments = {
                "paths": list(set(files)),
            }
            await thread_manager.execute_tool_and_add_message(thread_id, 'view', file_view_arguments)

    while total_iterations < max_iterations:
        outer_iteration += 1
        inner_iteration = 0

        messages = await thread_manager.list_messages(thread_id)
        for i in range(len(messages) - 1, -1, -1):
            await thread_manager.remove_message(thread_id, i)

        system = system_prompt.format(
            problem_statement=problem_statement,
            workspace_state=summary_tool.format_workspace_summary(workspace_state)
            )
        system_message = {
            "role": "system",
            "content": system
        }

        await thread_manager.add_message(thread_id, system_message)
        workspace_state = await state_manager.get('workspace_state')
        
        if total_iterations == 0:
            await thread_manager.add_message(thread_id, {
                "role": "user", 
                "content": user_prompt.format(
                    problem_statement=problem_statement,
                    workspace_state=summary_tool.format_workspace_summary(workspace_state)
                    )
            })
        else:
            await thread_manager.add_message(thread_id, {
                "role": "user",
                "content": continuation_prompt.format(
                    problem_statement=problem_statement,
                    workspace_state=summary_tool.format_workspace_summary(workspace_state)
                )
            })

            # await thread_manager.add_message(thread_id, {
            #     "role": "user",
            #     "content": """Here's the current workspace state, what we have so far: <workspace_state>\n{workspace_state}\n</workspace_state>
            #     You can find below the current ACTUAL CONTENT of editing files and folders in the explorer. Continue working from here. Do not view these files again.
            #     """.format(workspace_state=summary_tool.format_workspace_summary(workspace_state))
            # })

            await execute_view_commands(thread_manager, thread_id, workspace_state)

            # files = workspace_state.get('open_files_in_code_editor', [])
            # if files:
            #     bash_command_arguments = {
            #         "command": f"(git add -N . && git diff -- {' '.join(files)}) || echo 'No changes in open files'"
            #     }
            #     await thread_manager.execute_tool_and_add_message(thread_id, 'bash_command', bash_command_arguments)

            # Execute test commands
            test_commands = workspace_state.get('test_commands', [])
            for cmd in test_commands:
                bash_test_arguments = {
                    "command": cmd
                }
                await thread_manager.execute_tool_and_add_message(thread_id, 'bash_command', bash_test_arguments)

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

            # Add SummaryTool and reset at iteration 5
            if inner_iteration == reset_interval:
                thread_manager.add_tool(SummaryTool, state_file=state_file)
                await thread_manager.add_message(thread_id, {
                    "role": "user",
                    "content": (
                        "Time's up! Please review your checklist of tasks and indicate which tasks have been completed. "
                        "Have you met all the requirements specified in the PR description? Ensure that you have followed all the steps, "
                        "including analyzing the issue, implementing minimal changes without affecting existing tests, and handling edge cases. "
                        "If you have completed all tasks and are confident that the issue is resolved, please submit your fix. "
                        "Otherwise, you must summarize the current state of the workspace without doing anything else and provide instructions "
                        "for the next iteration using SummaryTool."
                    )
                })
                tool_choice={"type": "function", "function": {"name": "summarize"}}
            else:
                tool_choice="any"

            response = await thread_manager.run_thread(
                thread_id=thread_id,
                system_message=system_message,
                model_name=model_name_full,
                temperature=0.0,
                max_tokens=8192,
                tool_choice=tool_choice,
                native_tool_calling=not use_xml,
                xml_tool_calling=use_xml,
                execute_tools_on_stream=True,
                parallel_tool_execution=False,
            )

            assistant_messages = await thread_manager.list_messages(thread_id, only_latest_assistant=True)
            if assistant_messages:
                last_assistant = assistant_messages[0]
                tool_calls = last_assistant.get('tool_calls', [])
                for tool_call in tool_calls:
                    if tool_call['function']['name'] == 'submit':
                        print("Task completed via submit tool, stopping...")
                        return
        
        if total_iterations < max_iterations:
            await thread_manager.add_to_history_only(thread_id, {
                "role": "switch",
                "content": "--- Resetting workspace state ---"
            })

            # Reset thread messages
            messages = await thread_manager.list_messages(thread_id)
            for i in range(len(messages) - 1, -1, -1):
                await thread_manager.remove_message(thread_id, i)

        

    print(f"Agent completed after {total_iterations} total iterations ({outer_iteration} reset cycles)")

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
        parser.add_argument("--reset-interval", type=int, default=8, help="Number of iterations before state reset")
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