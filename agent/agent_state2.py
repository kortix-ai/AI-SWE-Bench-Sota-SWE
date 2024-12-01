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


system_prompt = """You are an autonomous expert software engineer specializing in implementing precise, high-quality modifications to resolve specific issues within a Python code repository.

CORE PRINCIPLES:
1. Systematic Analysis
   - Thoroughly analyze all provided workspace content
   - Examine opened files, folders, and PR description in detail
   - Build a complete mental model before proposing solutions
   - Base all reasoning on the provided workspace - avoid assumptions

2. Methodical Reasoning
   - Break down complex problems into smaller components
   - Consider each component's implications and interactions
   - Document your thought process at each step
   - Analyze in detail the content of the opened files in the workspace

3. Comprehensive Evaluation
   - Consider multiple approaches before selecting a solution
   - Evaluate trade-offs, potential drawbacks, and failure modes for each solution
   - Think through edge cases
   - Prioritize robustness and correctness over simplicity when necessary
   - Consider how changes might affect other parts of the system

CRITICAL GUIDELINES:
- Base ALL reasoning on the provided workspace - avoid assumptions
- Only modify files that are opened in the workspace
- After using `<open_file>` and `<view_folder>` actions, their content is only available in the next iteration
- Take time to deeply understand the context before making changes
- Think through potential side effects of each modification
- Track all implementation approaches using the track_implementation tool after running tests
- Check tests directories to make sure test paths exist

TECHNICAL REQUIREMENTS:
- Use exactly one `<ACTIONS>` tag containing all actions at the end
- Propose multiple solution approaches with detailed code snippets
- Always run tests after modifications at the end of `<ACTIONS>` tag
- Only modify files that are opened in the workspace
- DO NOT create new test files - modify existing ones only
- Do not edit any file that is not opened yet in the workspace

REASONING FRAMEWORK:
1. Initial Assessment
   - What is the core problem?
   - What context do we have?
   - What files are relevant?

2. Deep Analysis
   - How do the components interact?
   - What are the key dependencies?
   - Where could issues arise?

3. Solution Design
   - What are all possible approaches?
   - What are the trade-offs?
   - Which solution best fits the context?
   - Prioritize robustness and correctness over simplicity when necessary

4. Implementation Planning
   - What specific changes are needed?
   - In what order should changes be made?
   - How can we verify each step?

ALWAYS:
- Take a step back to see the bigger picture
- Think deeply about each decision
- Proceed step-by-step with careful consideration
- Question your assumptions
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

SYSTEMATIC APPROACH REQUIRED:

1. INITIAL ASSESSMENT
   - Review workspace files and PR description
   - Identify key components and relationships
   - Document initial observations and concerns
   - Ensure relevant files and existing tests are opened
   - Understand their functionality and relation to PR description

2. DETAILED ANALYSIS
   - Examine relevant files in depth
   - Map dependencies and interactions
   - Identify potential impact areas
   - Review last attempt if available
   - Analyze test command outputs if previous attempt failed

3. SOLUTION EXPLORATION
   - Consider multiple approaches
   - Document pros and cons, potential drawbacks, and failure modes for each
   - Think through edge cases
   - Consider maintenance implications
   - Track each implementation approach after running tests, using track_implementation tool at the end of your response, with detailed notes about the approach, code snippets, and analysis
   - Propose multiple solutions with code snippets

4. IMPLEMENTATION STRATEGY
   - Break down changes into logical steps
   - Plan verification points
   - Consider rollback scenarios
   - Choose the best solution that:
     * Fully addresses the root cause
     * Maintains existing functionalities
     * Ensures all tests pass
     * Does not introduce regressions
     * Prioritizes correctness and robustness over simplicity when necessary

REQUIRED STEPS:
1. Open and analyze relevant files, folders, and tests
2. Review previous attempts if available
3. Document your complete reasoning process using:
   - `<ASSESS_LAST_TRY>`: Detail review previous attempt results
     * Compare the changes made in the last attempt with the original code
     * Critically evaluate alternative implementation strategies
     * Determine next steps: improve current solution, update dependent code, or pursue alternative approach
   - `<OBSERVE_WORKSPACE>`: Analyze and document current workspace state
   - `<REASON>`: Detail your step-by-step thinking
   - `<PROPOSE_SOLUTIONS>`: List multiple approaches
   - `<POSSIBLE_FIX>`: Document selected solution rationale

IMPLEMENTATION GUIDELINES:
- Start fresh with "git reset --hard" if last attempt failed
- Execute multiple actions as needed
- Always run tests after modifications
- Wait for action results before proceeding
- Modify existing tests only - DO NOT create new test files
- If you require output of an action to proceed, wait for results

CRITICAL REMINDERS:
- Take time to think deeply about each step
- Consider all implications before making changes
- Document your reasoning thoroughly
- Validate assumptions
- Consider long-term maintainability
- If tests are not found, examine the relevant "tests" directory to locate the correct test paths

**IMPORTANT: If the last try solution was correct and all test cases passed, including existing tests and newly added tests specified for the PR, submit directly without proposing further solutions or implementations.**

You will operate autonomously from this point forward. Begin with the `<ASSESS_LAST_TRY>` tag, followed by `<OBSERVE_WORKSPACE>`, `<REASON>`, `<PROPOSE_SOLUTIONS>`, and `<POSSIBLE_FIX>` tags to document your thought process. Finally, list all actions within the `<ACTIONS>` tag. Your thinking should be thorough, and it's fine if it's very long.

ALWAYS TAKE A STEP BACK. THINK DEEPLY AND STEP BY STEP.
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
    }
    await thread_manager.add_to_history_only(thread_id, system_message)

    iteration = 0

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
                Based on the previous actions and their results, continue implementing the necessary changes.
                
                Remember to:
                1. Review the current state and previous actions
                2. Think step-by-step about the next logical changes
                3. Validate each change against the PR requirements
                4. Consider potential edge cases and implications
                
                CONTINUE IMPLEMENTING THE NECESSARY CHANGES TO THE REPO SO THE REQUIREMNTS In <pr_description> are met.  MAKE SURE TO TAKE A STEP BACK. THINK DEEPLY AND STEP BY STEP.
                """
                temporary_message = {
                    "role": "user", 
                    "content": continuation_prompt
                }

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
                temporary_message=temporary_message  # Add the temporary message parameter
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