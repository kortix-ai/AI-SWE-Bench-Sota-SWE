import json
import asyncio
import argparse
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from tools.files_tool import FilesTool
from agentpress.state_manager import StateManager
from tools.terminal_tool import TerminalTool

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 10, model_name: str = "sonnet"):
    thread_manager = ThreadManager(threads_dir=threads_dir)
    state_manager = StateManager(store_file="state.json")

    async def after_iteration():

        message_content = """ 
        Run test to check if the bug is fixed, if all tests pass, output "FINISHED" without any other text.
        """
        await thread_manager.add_message(thread_id, {
            "role": "user", 
            "content": message_content
        })

    with open(problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    # thread_manager.add_tool(FilesTool, container_name=container_name)
    # thread_manager.add_tool(TerminalTool, container_name=container_name)
    from tools.repo_tool import RepositoryTools
    thread_manager.add_tool(RepositoryTools, container_name=container_name)

    system_message = """
You are an expert software engineer specializing in code analysis and problem-solving within complex codebases. Your purpose is to understand PR requirements thoroughly and implement precise, minimal changes that solve the described issues while maintaining high code quality and backward compatibility. 

**Your Approach Should Include:**

- **Deep Codebase Exploration:**
  - Read and analyze multiple related files to fully understand the system.
  - Consider the impact of changes on the entire codebase.

- **Systematic Problem Analysis:**
  - Identify the root cause of the issue.
  - Consider all possible edge cases and existing functionalities that may be affected.

- **Thoughtful Implementation:**
  - Develop a detailed plan before making changes.
  - Ensure your solution is in line with the project's design principles.

- **Comprehensive Testing:**
  - Create and run scripts to reproduce and verify the issue.
  - Run the full test suite to ensure no new issues are introduced.

- **Reflective Iteration:**
  - Review your changes critically.
  - Be prepared to adjust your solution based on test results and further insights.

Work systematically: analyze the problem thoroughly, implement solutions carefully, and verify your changes through extensive testing.

"""
    await thread_manager.add_message(thread_id, {
        "role": "system", 
        "content": system_message,
    })

    await thread_manager.add_message(thread_id, {
            "role": "user",
            "content": f"""
I have uploaded a Python code repository in the directory `/testbed`. Consider the following PR description:

<pr_description>
{problem_statement}
</pr_description>

Can you help me implement the necessary changes to the repository so that the requirements specified in the `<pr_description>` are met?

**Important Instructions:**

- **Focus on Non-Test Files:**
  - Do not modify any test files or testing logic.
  - Your changes should be limited to the source code files.

- **Limited Access:**
  - You do not have access to any new tests that may have been added.
  - You should reason about the problem and create necessary scripts for testing on your own.

**Steps to Resolve the Issue:**

1. **Explore the Repository:**
   - Familiarize yourself with the repository structure and relevant modules.
   - Read multiple related files to understand how they interact.

2. **Reproduce the Issue:**
   - Create a script to reproduce the error.
   - Execute it using `python <filename.py>` to confirm the problem exists.

3. **Analyze the Root Cause:**
   - Investigate why the issue occurs.
   - Consider how different parts of the codebase contribute to the problem.

4. **Plan Your Solution:**
   - Outline your proposed changes.
   - Think about how your changes will affect other functionalities.

5. **Implement the Fix:**
   - Make minimal and precise changes to the source code to resolve the issue.
   - Ensure your changes adhere to coding standards and best practices.

6. **Test Thoroughly:**
   - Rerun your reproduction script to confirm the issue is fixed.
   - Run all relevant existing tests to ensure no new issues have been introduced.
   - Consider edge cases and ensure your fix handles them appropriately.

7. **Review and Refine:**
   - Reflect on your solution.
   - Make any necessary adjustments based on test results or further analysis.

**Response Format:**

- **<observations>**
  - State the problem and your understanding of it.
  
- **<thoughts>**
  - Provide a detailed plan for your changes.
  - Consider potential impacts and edge cases.
  
- **<actions>**
  - Include multiple tool calls, such as reading files, running scripts, etc.
  - Show your step-by-step process.

Your response should be thorough and demonstrate a deep understanding of the issue and the codebase.

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
            # system_message=system_message,
            model_name=model_name_full,
            temperature=0.1,
            max_tokens=4096,
            tool_choice="auto",
            execute_tools_async=True,
            use_tools=True,
            execute_model_tool_calls=True
        )

        print(f"Iteration {iteration}/{max_iterations}:")
        # print(response)

        if "FINISHED" in response:
            print("Bug fixed, stopping...")
            break

        # await after_iteration()

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
