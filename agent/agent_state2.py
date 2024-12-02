import json
import asyncio
import argparse
import os
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
import agentops

agentops.init(os.environ['AGENTOPS_API_KEY'])
agentops.init(os.environ['OPENROUTER_API_KEY'])

system_prompt = """You are an autonomous expert software engineer tasked with making precise, high-quality modifications to resolve specific issues in a Python code repository. Your goal is to analyze the problem, propose solutions, and implement the best fix while maintaining code quality and efficiency.

Available XML tools to interact with the workspace:
<xml_tools>
{xml_format}
</xml_tools>
"""

user_prompt = """First, examine the current state of the workspace:
{workspace}

Now, review the following XML tools that you'll use to interact with the workspace:

<xml_tools>
{xml_format}
</xml_tools>

A Python code repository has been uploaded to the `/testbed` directory. Consider the following PR description:

<pr_description>
{problem_statement}
</pr_description>

Follow this systematic approach to address the issue:

1. Initial Assessment
   - Review workspace files and the PR description.
   - Identify key components and their relationships.
   - Document your initial observations and concerns.
   - Ensure relevant files and existing tests are opened.
   - Understand their functionality in relation to the PR description.

2. Detailed Analysis
   - Examine relevant files in depth.
   - Map out dependencies and interactions between components.
   - Identify areas that may be impacted by changes.
   - If available, review the last attempt and analyze test outputs if it failed.

3. Solution Exploration
   - Consider multiple approaches to solve the problem.
   - For each approach, document:
     - Pros and cons
     - Potential drawbacks
     - Possible failure modes
   - Think through edge cases and maintenance implications.
   - Propose multiple solutions.
   - If <IMPLEMENTATION_TRAILS> are available:
     - Review existing trials
     - Update their status based on the last attempt results
     - Analyze what worked and what didn't
     - Modify approaches based on your learnings
   - Use the `track_implementation` tool within <PROPOSE_SOLUTIONS> to:
     - Add new trials if necessary
     - Update existing trials
     - Include detailed notes.
     - Update status appropriately
   - Ensure comprehensive coverage of the solution space.
   - If the current implementation fails multiple times:
     - Document the failure in detail
     - Use `git reset --hard` to start fresh
     - Try the next best solution approach
     - Keep iterating until you find a working solution
   - Never settle for partial success - all tests must pass.

4. Implementation Strategy
   - Break down the changes into logical steps.
   - Plan verification points throughout the implementation.
   - Consider potential rollback scenarios.
   - Choose the best solution that:
     - Fully addresses the root cause of the issue
     - Maintains existing functionalities
     - Does not introduce regressions
     - Prioritizes correctness and robustness over simplicity when necessary

Important Guidelines:
- Base all reasoning on the provided workspace; avoid making assumptions.
- Only modify files that are opened in the workspace.
- Deeply understand the context before making any changes.
- Consider potential side effects of each modification.
- Check test directories to ensure test paths exist.
- Append new tests for PR by modifying existing tests files only, but never edit existing testcases.
- Keep iterating with different approaches until all tests pass.
- Do not give up if tests fail; always try alternative solutions.

Document your complete reasoning process by wrapping your analysis in these tags:
- <PREVIOUS_ATTEMPT_ANALYSIS>: Review previous attempt results, including what worked, what failed, and potential reasons for failure.
- <OBSERVE_WORKSPACE>: Analyze the current workspace state, listing key files, their purposes, and notable dependencies between them.
- <REASON>: Detail your step-by-step thinking, including consideration of edge cases and potential side effects.
- <PROPOSE_SOLUTIONS>: List multiple best approaches, minimal or complex, to solve the problem, including code snippets and analysis.
- <POSSIBLE_FIX>: Document the selected solution rationale.

Implementation Guidelines:
- Start fresh with `git reset --hard` if the last attempt failed.
- Execute multiple actions as needed.
- Always run tests after modifications and add new tests to confirm the PR.
- Wait for action results before proceeding.
- Modify existing tests only.
- Use `track_implementation` in <PROPOSE_SOLUTIONS>.

Critical Reminders:
- Think deeply about each step.
- Consider all implications before making changes.
- Document your reasoning thoroughly.
- Validate your assumptions.
- Consider long-term maintainability.
- If tests are not found, examine the relevant `tests` directory to locate correct test paths.
- Update trial status and notes based on previous attempts.
- Ensure new tests for this PR are created and executed.
- Only propose solutions, edit file when all relevant files are already opened in the workspace.
- Only run tests after having the correct test paths.

Only submit your changes when both of these conditions are strictly met:

1. All test cases pass completely (including existing and newly added tests specified for the PR). This includes verifying that the code runs correctly and passes all tests without errors.

2. The implemented changes correctly and completely address the requirements in the PR description with appropriate and correct code modifications.

**If either condition is not fully satisfied, do not submit your changes. Continue iterating with alternative solutions.**

**Do not output `<PR_SOLVED_SUBMIT_AND_TERMINATE />` unless you are completely certain that both conditions are fully satisfied.**

You will operate autonomously from this point forward.
Begin your analysis and problem-solving process with the `<PREVIOUS_ATTEMPT_ANALYSIS>` tag, followed by `<OBSERVE_WORKSPACE>`, `<REASON>`, `<PROPOSE_SOLUTIONS>`, and `<POSSIBLE_FIX>` tags to document your thought process. 
Finally, list all actions within the `<ACTIONS>` tag and await the results. 

Think deeply and proceed step-by-step through each stage of the process. Your thinking should be thorough, and it's fine if it's very long.
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
        "content": system_prompt.format(xml_format=xml_format)
    }
    await thread_manager.add_to_history_only(thread_id, system_message)

    iteration = 0
    reminder_custom_test = False

    while iteration < max_iterations:
        try:
            iteration += 1
            stdout, _, _ = await repo_tool._bash_executor.execute('git diff')
            await thread_manager.add_to_history_only(thread_id, {
                "role": "git diff",
                "content": f"{stdout if stdout else 'No changes'}"
            })

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

            # Add continuation prompt for iterations after the first
            temporary_message = None
            if iteration > 1:
                continuation_prompt = """
                Based on previous actions and results, continue implementing the necessary changes.

                Remember to:
                1. Review the current state and previous actions.
                2. Think step-by-step about the next logical changes.
                3. Validate each change against the PR requirements.
                4. Consider potential edge cases and implications.

                CONTINUE IMPLEMENTING THE NECESSARY CHANGES TO THE REPO SO THE REQUIREMENTS IN <pr_description> ARE MET. TAKE A STEP BACK, THINK DEEPLY AND STEP BY STEP.
                """
                temporary_message = {
                    "role": "user", 
                    "content": continuation_prompt
                }
                if reminder_custom_test:
                    temporary_message = {
                        "role": "user",
                        "content": continuation_prompt + "\n\n# **IMPORTANT**: Have you created and run new tests specified for this PR? If not, please do so now."

                    }
                    reminder_custom_test = False

            response = await thread_manager.run_thread(
                thread_id=thread_id,
                system_message=system_message,
                model_name=model_name,
                temperature=0.0,
                max_tokens=8096,
                tool_choice="any",
                native_tool_calling=False,
                xml_tool_calling=True,
                parallel_tool_execution=False,
                temporary_message=temporary_message, 
                stop_sequences=["</ACTIONS>"] 
            )

            assistant_messages = await thread_manager.list_messages(thread_id, only_latest_assistant=True)
            if assistant_messages:
                last_assistant = assistant_messages[0]['content']
                try:
                    if "PR_SOLVED_SUBMIT_AND_TERMINATE" in last_assistant:
                        if iteration > 5:
                            print("Task completed via mark_pr_as_solved tool, stopping...")
                            agentops_session.end_session()
                            return
                        else:
                            reminder_custom_test = True
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
                "gpt-4o": "o1-preview",
                "qwen": "openrouter/qwen/qwq-32b-preview",
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