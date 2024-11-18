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

system_prompt = """
You are an autonomous expert software engineer focused on implementing precise, minimal changes to solve specific issues.
<IMPORTANT>\n*After using a tool to make changes to a file, immediately run a bash command to run script.\n</IMPORTANT>\n
"""



user_prompt = """
<uploaded_files>
/testbed/
</uploaded_files>
I've uploaded a python code repository in the directory /testbed/. Consider the following PR description:

<pr_description>
{problem_statement}
</pr_description>

Can you help me implement the necessary changes to the repository so that the requirements specified in the <pr_description> are met? 
I've already taken care of all changes to any of the test files described in the <pr_description>. This means you DON'T have to modify the testing logic or any of the tests in any way! 
Your task is to make the minimal changes to non-tests files in the /repo directory to ensure the <pr_description> is satisfied. 
Follow these steps to resolve the issue: 
1. As a first step, it might be a good idea to explore the repo to familiarize yourself with its structure. 
2. Create a script to reproduce the error and execute it with `python <filename.py>` using the BashTool, to confirm the error 
3. Edit the sourcecode of the repo to resolve the issue 
4. Rerun your reproduce script and confirm that the error is fixed! 
5. Think about edgecases and write edge cases test script to test the edge cases. Make sure your fix handles them as well!

After editing or creating files, always use bash tool immediately, as they are working sequentially. Use <thoughts> and <actions> tags before using any tools. Your thinking should be thorough and so it's fine if it's very long.

"""

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 10, reset_interval: int = 8, model_name: str = "sonnet"):
    thread_manager = ThreadManager(threads_dir=threads_dir)
    state_file = os.path.join(threads_dir, thread_id, 'state.json')
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state_manager = StateManager(store_file=state_file)
    use_xml = False

    # Initialize workspace state
    initial_workspace = {
        "explorer_folders": [],
        "open_files_in_code_editor": [],
        "thinking_logs": [],
        "terminal_session": []
    }
    await state_manager.set('workspace_state', initial_workspace)

    with open(problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    from tools.repo_tool import RepositoryTools
    thread_manager.add_tool(RepositoryTools, container_name=container_name, state_file=state_file)

    from tools.edit_tool import EditTool
    from tools.bash_tool import BashTool
    thread_manager.add_tool(EditTool, container_name=container_name, state_file=state_file)
    thread_manager.add_tool(BashTool, container_name=container_name, state_file=state_file)
    summary_tool = SummaryTool(state_file=state_file)

    outer_iteration = 0
    total_iterations = 0

    while total_iterations < max_iterations:
        outer_iteration += 1
        inner_iteration = 0

        messages = await thread_manager.list_messages(thread_id)
        for i in range(len(messages) - 1, -1, -1):
            await thread_manager.remove_message(thread_id, i)

        system = system_prompt.format(problem_statement=problem_statement)
        system_message = {
            "role": "system",
            "content": system
        }

        await thread_manager.add_message(thread_id, system_message)
        workspace_state = await state_manager.get('workspace_state')
        
        await thread_manager.add_message(thread_id, {
            "role": "user", 
            "content": user_prompt.format(
                problem_statement=problem_statement,
                workspace_state=summary_tool.format_workspace_summary(workspace_state)
            )
        })

        if total_iterations != 0:
            await thread_manager.add_message(thread_id, {
                "role": "user",
                "content": """Here's the current workspace state, what we have so far: <workspace_state>\n{workspace_state}\n</workspace_state>""".format(workspace_state=summary_tool.format_workspace_summary(workspace_state))
            })


            await thread_manager.add_message_and_run_tools(thread_id, {
                "role": "user",
                'content': "Here's the content of opening files in the current workspace and changes made:",
                "tool_calls": [
                    {
                        "id": str(uuid.uuid4()),
                        "type": "function",
                        "function": {
                            "name": "view",
                            "arguments": json.dumps({
                                "paths": list(set(workspace_state.get('explorer_folders', []) + workspace_state.get('open_files_in_code_editor', [])))
                            })
                        }
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "type": "function",
                        "function": {
                            "name": "bash_command",
                            "arguments": json.dumps({
                                "command": f"(git add -N . && git diff -- {' '.join(workspace_state.get('open_files_in_code_editor', []))}) || echo 'No changes in open files'"
                            })
                        }
                    }
                ]
            })

        while inner_iteration < reset_interval and total_iterations < max_iterations:
            inner_iteration += 1
            total_iterations += 1

            # Add SummaryTool and reset at iteration 5
            if inner_iteration == reset_interval:
                thread_manager.add_tool(SummaryTool, state_file=state_file)
                await thread_manager.add_message(thread_id, {
                    "role": "user",
                    "content": "Time's up! 1. Have you fixed the issue? 2. Is the reproduce error test file fully functional? 3. Have you considered all possible edge cases by writing and running edge cases test script?\nIf you're confident that the issue is solved, please submit. Otherwise, you **MUST summarize** the current state of the workspace without doing anything else and provide instructions for the next iteration using SummaryTool."
                })

            model_mapping = {
                "sonnet": "anthropic/claude-3-5-sonnet-latest",
                "haiku": "anthropic/claude-3-5-haiku-latest",
                "deepseek": "deepseek/deepseek-chat",
                "gpt-4o": "gpt-4o",
                "qwen": "openrouter/qwen/qwen-2.5-coder-32b-instruct",
            }
            model_name_full = model_mapping.get(model_name, "anthropic/claude-3-5-sonnet-latest")

            print(f"Iteration {total_iterations}/{max_iterations} (Reset cycle {outer_iteration}, Step {inner_iteration})")

            response = await thread_manager.run_thread(
                thread_id=thread_id,
                system_message=system_message,
                model_name=model_name_full,
                temperature=0.0,
                max_tokens=8192,
                tool_choice="any",
                native_tool_calling=not use_xml,
                xml_tool_calling=use_xml,
                # temporary_message=messages,
                # execute_tools_async=False,
                # use_tool=True,
                execute_tools_on_stream=True,
                parallel_tool_execution=False,
            )

            # Check for 'submit' tool call
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