import json
import asyncio
import argparse
import os
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
import agentops

agentops.init(os.environ['AGENTOPS_API_KEY'])


system_prompt = """You are an autonomous expert software engineer focused on implementing precise, high-quality changes to solve specific issues in a Python code repository while passing existing tests.

STRICTLY OUTPUT YOUR ACTIONS IN THE FOLLOWING XML FORMAT WITHIN A SINGLE <ACTIONS> TAG:

<AVAILABLE_XML_TOOLS>
{xml_format}
</AVAILABLE_XML_TOOLS>

GUIDELINES:

1. Use only one <ACTIONS> tag containing all actions. Do not use multiple <ACTIONS> tags.
2. Do not repeat tags or output multiple instances of the same tag.
3. Do not produce any output after the closing </ACTIONS> tag. Wait for the results of action execution.

THOUGHT PROCESS TAGS (use these before the <ACTIONS> tag):

1. <ASSESS_LAST_TRY>: If a <last_try> is provided, review it critically. Decide whether to submit, continue from it, or start over.
2. <OBSERVE>: Note relevant information from the codebase based on the <file> tags of the workspace. Do not assume file contents or command outputs beyond what is provided.
3. <REASON>: Determine the necessary changes to solve the issue described in the PR. Identify the root cause based on your observations.
4. <MULTIPLE_POSSIBLE_FIX>: If appropriate, propose multiple solutions. For each solution, provide code snippets and a deep analysis explaining its impact on the codebase functionalities and existing tests. Choose the best solution to implement, ensuring it fully addresses the issue.

INSTRUCTIONS:

- Prioritize correctness and code quality over making minimal changes.
- Select the best solution that fully addresses the root cause while maintaining existing functionalities and passing all tests.
- In the <ACTIONS> tag, list all actions using the available XML tools, including modifications, file creations, and command executions.
- Use "git reset --hard" at the start of <ACTIONS> if you decide to start from scratch.
- Run tests to confirm the issue is fixed.
- **You can only use `<mark_pr_as_solved />` after you have assessed the last try using `<ASSESS_LAST_TRY>`.**

REMEMBER:

- Be clear and precise in your analysis and actions.
- The goal is to pass all existing tests while fixing the issue described in the PR.
- Base all your reasoning on the provided workspace and PR description.
- Do not make assumptions beyond the given information.
"""

user_prompt = """The current state of the repository is as follows:
{workspace}

A Python code repository has been uploaded to the `/testbed` directory. Please consider the following PR description:

<pr_description>
{problem_statement}
</pr_description>

Can you help me implement the necessary changes to the repository to meet the requirements specified in the <pr_description>?

Additional Instructions:

- Assess the last attempt first if a <last_try> is provided. Decide whether to submit it and terminate (if the fix was correct and all test cases passed), continue from it, or start over with "git reset --hard".
- Ensure you have all relevant context before making any changes. Do not hesitate to open new files related to the issue if necessary.
- Modify and run test files to confirm the issue is fixed. Use the `-q -ra` options to only show failed test cases (e.g., `<run_command command="python -m pytest /testbed/.../test_example.py -q -ra" />`).
- After closing the `</ACTIONS>` tag, wait for the results of action execution without producing further output.

Please proceed to analyze the PR and implement the required changes using the guidelines provided.
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
            if iteration > 5:
                assistant_messages = await thread_manager.list_messages(thread_id, only_latest_assistant=True)
                if assistant_messages:
                    last_assistant = assistant_messages[0]['content']
                    try:
                        # Look for mark_pr_as_solved tag in the response
                        if '<mark_pr_as_solved />' in last_assistant:
                            print("Task completed via mark_pr_as_solved tool, stopping...")
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

    asyncio.run(main())