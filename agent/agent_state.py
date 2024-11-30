import json
import asyncio
import argparse
import os
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
import agentops

agentops.init(os.environ['AGENTOPS_API_KEY'])


system_prompt = """You are an autonomous expert software engineer specializing in implementing precise, high-quality modifications to resolve specific issues within a Python code repository.

- Base all reasoning on the provided workspace, including opened files, folders, and the PR description. Do not make assumptions beyond the provided information.
- Analyze in detail the content of the opened files in the current workspace.

IMPORTANT:
- Use only one `<ACTIONS>` tag containing all your actions at the end of your response.
- Propose multiple solutions or possible approaches with code snippets for each related file, each approach may involve different files.
- Always run tests after making modifications at the end of `<ACTIONS>` tag to ensure the code functions as expected.
- Do not any edit file that is not opened yet in the workspace.
- DO NOT CREATE NEW TEST FILES, you only can modify existing test files.
"""
user_prompt = """Below is the current state of the workspace:
{workspace}

STRICTLY OUTPUT YOUR ACTIONS IN THE FOLLOWING XML FORMAT ENCLOSED WITH A SINGLE `<ACTIONS>` TAG:
<AVAILABLE_XML_TOOLS>
{xml_format}
</AVAILABLE_XML_TOOLS>

A Python code repository has been uploaded to the `/testbed` directory. Please consider the following PR description:
<pr_description>
{problem_statement}
</pr_description>

Can you assist in implementing the necessary changes to the repository to fulfill the requirements specified in the `<pr_description>`?

Guidelines:
- Initial Step: Ensure that relevant files and existing tests are opened, and their content is displayed in the workspace.
- Detailed Analysis of Workspace: Analyze in detail the opened files in the current workspace, understanding their functionality and how they relate to the PR description.
- Review Last Attempt: If a `<last_try>` tag is provided, critically review it and analyze the output of test commands. If it failed, think deeply about why it failed, if the last approach was incorrect.
- Analysis: Take time to evaluate the current state of the code and consider various approaches before making changes.
- Solution Exploration: Propose multiple solutions or possible approaches with code snippets, this may involve multiple different files.
- Solution Selection: Choose the best solution to implement that fully addresses the root cause, maintains existing functionalities, and ensures all tests pass.
- Edge Cases: Consider edge cases and ensure your fix handles them appropriately.
- Action Execution: If last attempt was failed, you should start fresh with "git reset --hard". You may perform multiple actions in your response. Make sure to always run tests after making modifications. However, if you require the output of an action to proceed, wait for the results before continuing. DO NOT CREATE NEW TEST FILES, you should find and update existing tests relevant to the issue instead if it isn't in workspace.

You will operate autonomously from this point forward. Begin with the `<ASSESS_LAST_TRY>` tag, followed by `<OBSERVE_WORKSPACE>`, `<REASON>`, `<PROPOSE_SOLUTIONS>` and `<POSSIBLE_FIX>` tags to document your thought process. Finally, list all actions within the `<ACTIONS>` tag and await the results. Your thinking should be thorough and so it's fine if it's very long.
"""

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 10, model_name: str = "sonnet"):
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

    await repo_tool._init_workspace()

    xml_examples = thread_manager.tool_registry.get_xml_examples()
    xml_format = f"{json.dumps(xml_examples, indent=2)}"
    system_message = {
        "role": "system",
        "content": system_prompt
        #.format(xml_format=xml_format)
    }
    await thread_manager.add_to_history_only(thread_id, system_message)

    iteration = 0

    while iteration < max_iterations:
        try:
            iteration += 1
            await thread_manager.reset_messages(thread_id)

            workspace = await repo_tool.format_workspace_xml()
            await thread_manager.add_message(thread_id, {
                "role": "user",
                "content": user_prompt.format(
                    problem_statement=problem_statement, 
                    workspace=workspace,
                    xml_format=xml_format,
                )
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
            )

            if iteration > 4:
                assistant_messages = await thread_manager.list_messages(thread_id, only_latest_assistant=True)
                if assistant_messages:
                    last_assistant = assistant_messages[0]['content']
                    try:
                        # if '<mark_pr_as_solved />' in last_assistant:
                        if "LAST TRY SUCCESSFUL, TERMINATING" in last_assistant:
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