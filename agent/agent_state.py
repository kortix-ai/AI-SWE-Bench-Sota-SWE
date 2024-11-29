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

STRICTLY OUTPUT YOUR ACTIONS IN THE FOLLOWING XML FORMAT IN A SINGLE <ACTIONS> TAG:
<AVAILABLE_XML_TOOLS>
{xml_format}
</AVAILABLE_XML_TOOLS>

- A <last_try> solution and its result may be provided for reference. Note that the codebase is reset to the original state, so rely solely on the code provided in the <file> tags of the workspace. Do not assume file contents or command outputs.
- If a <last_try> is provided, review it critically. Ensure the changes are minimal to solve the PR without breaking existing functionalities and tests. If the fix is correct and minimal, submit the PR.
- In <MULTIPLE_POSSIBLE_FIX>, provide multiple possible solutions to the issue with short code snippets to demonstrate the fix. Select the best solution that addresses the root cause while maintaining the codebase's functionalities.
- Use <ASSET_LAST_TRY>, <OBSERVE>, <REASON> and <MULTIPLE_POSSIBLE_FIX> tags to document your thought process. Finally, list all actions in the <ACTIONS> tag and wait for results.
- ONLY SUBMIT if the current fix is correct and all tests cases are passed. 
"""

user_prompt = """I've uploaded a Python code repository in the directory /testbed. Consider the following PR description:

<pr_description>
{problem_statement}
</pr_description>

Can you help me implement the necessary changes to the repository to meet the requirements specified in the <pr_description>?

The current state of the repository is as follows:
{workspace}

- Ensure you have all relevant context before making any changes. Do not hesitate to open new files related to the issue.
- Modify and run test files to confirm the issue is fixed, make sure it use -q -ra option to only show failed testcases (e.g. <run_command command="python -m pytest /testbed/.../test_example.py -q -ra 2>&1 | grep -v 'RuntimeWarning'" />).
"""


@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 10, model_name: str = "sonnet"):
    # Start agentops session at the beginning of run_agent
    agentops_session = agentops.start_session()
    
    thread_manager = ThreadManager(threads_dir=threads_dir)
    state_file = os.path.join(threads_dir, thread_id, 'state.json')
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state_manager = StateManager(store_file=state_file)

    with open(problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    from tools.repo_tool import RepositoryTools
    thread_manager.add_tool(RepositoryTools, container_name=container_name, state_manager=state_manager)
    repo_tool = RepositoryTools(container_name=container_name, state_manager=state_manager)

    # Initialize the workspace explicitly
    await repo_tool._init_workspace()

    # from tools.bash_tool import BashTool
    # thread_manager.add_tool(BashTool, container_name=container_name, state_file=state_file)
    # from tools.edit_and_run_tool import EditTool
    # thread_manager.add_tool(EditTool, container_name=container_name, state_file=state_file)
    # from tools.report_tool import ReportTool
    # report_tool = ReportTool(state_file=state_file)

    xml_examples = thread_manager.tool_registry.get_xml_examples()
    xml_format = f"{json.dumps(xml_examples, indent=2)}"
    system_message = {
        "role": "system",
        "content": system_prompt.format(xml_format=xml_format)
    }
    await thread_manager.add_to_history_only(thread_id, system_message)

    iteration = 0

    while iteration < max_iterations:
        try:
            iteration += 1
            await thread_manager.reset_messages(thread_id)

            # Retrieve the current workspace
            workspace = await repo_tool.format_workspace_xml()
            await thread_manager.add_message(thread_id, {
                "role": "user",
                "content": user_prompt.format(problem_statement=problem_statement, workspace=workspace)
            })

            response = await thread_manager.run_thread(
                thread_id=thread_id,
                system_message=system_message,
                model_name=model_name,
                temperature=0.0,
                max_tokens=8192,
                tool_choice="any",
                native_tool_calling=False,
                xml_tool_calling=True,
                parallel_tool_execution=False,
                # agentops_session=agentops_session,
            )

            # Check for submit in XML response
            assistant_messages = await thread_manager.list_messages(thread_id, only_latest_assistant=True)
            if assistant_messages:
                last_assistant = assistant_messages[0]['content']
                try:
                    # Look for submit tag in the response
                    if '<submit' in last_assistant:
                        print("Task completed via submit tool, stopping...")
                        agentops_session.end_session()
                        return
                except Exception as e:
                    print(f"Error parsing XML response: {str(e)}")
                    continue

        except Exception as e:
            print(f"Error in iteration {iteration}: {str(e)}")
            break

    print(f"Agent completed after {iteration} iterations")

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
        args = parser.parse_args()

        model_mapping = {
                "sonnet": "anthropic/claude-3-5-sonnet-latest",
                "haiku": "anthropic/claude-3-5-haiku-latest",
                "deepseek": "deepseek/deepseek-chat",
                "gpt-4o": "gpt-4o",
                "qwen": "openrouter/qwen/qwen-2.5-coder-32b-instruct",
            }

        model_name= model_mapping.get(args.model_name, "anthropic/claude-3-5-sonnet-latest")

        thread_manager = ThreadManager(threads_dir=args.threads_dir)
        thread_id = await thread_manager.create_thread()
        await run_agent(
            thread_id,
            args.container_name,
            args.problem_file,
            args.threads_dir,
            max_iterations=args.max_iterations,
            model_name=model_name
        )

    asyncio.run(main())