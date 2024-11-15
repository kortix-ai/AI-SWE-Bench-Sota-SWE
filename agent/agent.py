import json
import asyncio
import argparse
import os
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
import uuid

shared_knowledge_schema = """
The shared_knowledge is a JSON object with the following schema:
{
    'files_to_edit': [],
    'context_files': [],
    'detail_issue_analyze': "",
    'path_to_reproduce_error.py': "",
    'path_to_edge_cases.py': "",
}
"""

common_allowed_tools = ['view']

class TaskManager:
    def __init__(self, thread_manager, state_manager, tasks, shared_knowledge):
        self.thread_manager = thread_manager
        self.state_manager = state_manager
        self.tasks = tasks
        self.shared_knowledge = shared_knowledge

    async def run_tasks(self, thread_id, model_name, problem_statement):
        model_mapping = {
            "sonnet": "anthropic/claude-3-5-sonnet-latest",
            "haiku": "anthropic/claude-3-5-haiku-latest",
            "deepseek": "deepseek/deepseek-chat",
            "gpt-4o": "gpt-4o",
            "qwen": "openrouter/qwen/qwen-2.5-coder-32b-instruct",
        }
        model_name_full = model_mapping.get(model_name, "anthropic/claude-3-5-sonnet-latest")

        for task in self.tasks:
            print(f"Starting task: {task['name']}")

            await self.thread_manager.add_to_history_only(thread_id, {
                "role": "task-switch",
                "content": f"--- Task switched to {task['name']} ---"
            })
            await self.thread_manager.reset_thread_messages(thread_id)

            if task['name'] == 'Exploration':
                await self.thread_manager.add_message(thread_id, {
                    "role": task['user_prompt']['role'],
                    "content": task['user_prompt']['content'].format(
                        problem_statement=problem_statement,
                        shared_knowledge_schema=shared_knowledge_schema
                    )
                })
                await self.thread_manager.run_tool_as_message(
                    thread_id,
                    'view',
                    {'paths': ['/testbed'], 'depth': 1},
                    role='user'
                )
            elif task['name'] == 'Analysis and Implementation':
                shared_knowledge = await self.state_manager.get('shared_knowledge') or {}

                await self.thread_manager.add_message(thread_id,{
                    "role": task['user_prompt']['role'],
                    "content": task['user_prompt']['content'].format(
                        problem_statement=problem_statement,
                        shared_knowledge=json.dumps(shared_knowledge)
                    )
                })

                paths = shared_knowledge.get('selected_related_folders', []) + \
                        shared_knowledge.get('related_files', []) + \
                        shared_knowledge.get('context_files', []) 

                await self.thread_manager.run_tool_as_message(
                    thread_id,
                    'view',
                    {'paths': paths},
                    role='user'
                )
            else:
                shared_knowledge = await self.state_manager.get('shared_knowledge') or {}

                await self.thread_manager.add_message(thread_id,{
                    "role": task['user_prompt']['role'],
                    "content": task['user_prompt']['content'].format(
                        problem_statement=problem_statement,
                        shared_knowledge=json.dumps(shared_knowledge)
                    )
                })

                paths = shared_knowledge.get('selected_related_folders', []) + \
                        shared_knowledge.get('related_files', []) + \
                        shared_knowledge.get('context_files', []) 

                await self.thread_manager.run_tool_as_message(
                    thread_id,
                    'view',
                    {'paths': paths},
                    role='user'
                )



            allowed_tools = task.get('allowed_tools', []) + common_allowed_tools

            iteration = 0
            task_completed = False
            while iteration < task['max_iterations'] and not task_completed:
                iteration += 1

                if iteration == task['max_iterations']:
                    await self.thread_manager.add_message(thread_id, {
                        "role": "user",
                        "content": "Time's up! Please use submit tool to submit the task."
                    })

                response = await self.thread_manager.run_thread(
                    thread_id=thread_id,
                    system_message=task['system_prompt'],
                    model_name=model_name_full,
                    temperature=0.0,
                    max_tokens=4096,
                    tool_choice="auto",
                    execute_tools_async=False,
                    use_tools=True,
                    execute_model_tool_calls=True,
                    allowed_tools=allowed_tools
                )

                assistant_messages = await self.thread_manager.list_messages(thread_id, only_latest_assistant=True)
                if assistant_messages:
                    last_assistant = assistant_messages[0]
                    tool_calls = last_assistant.get('tool_calls', [])
                    for tool_call in tool_calls:
                        if tool_call['function']['name'] in ['submit', 'submit_with_summary']:
                            print(f"Task '{task['name']}' completed via submit tool, moving to next task...")
                            task_completed = True
                            break

        print("Agent completed all tasks.")

@observe()
async def run_agent(thread_id: str, container_name: str, problem_file: str, threads_dir: str, max_iterations: int = 10, model_name: str = "sonnet"):
    thread_manager = ThreadManager(threads_dir=threads_dir)
    state_file = os.path.join(threads_dir, thread_id, 'state.json')
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state_manager = StateManager(store_file=state_file)

    with open(problem_file, 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    from tools.repo_tool import RepositoryTools
    from tools.submit_with_summary_tool import SubmitWithSummaryTool

    thread_manager.add_tool(RepositoryTools, container_name=container_name, state_file=state_file)
    thread_manager.add_tool(SubmitWithSummaryTool, state_file=state_file)

    tasks = [
            {
                'name': 'Exploration',
                'system_prompt': {
                    "role": "system",
                    "content": "You are a helpful assistant specialized in exploring code repositories and preparing tests. Your discoveries will help  developer to implement the necessary changes."
                },
                'user_prompt': {
                    "role": "user",
                    "content": """
<uploaded_files>
/testbed/
</uploaded_files>
I've uploaded a python code repository in the directory /testbed. Consider the following PR description:
<pr_description>
{problem_statement}
</pr_description>

Can you help me explore the repository to understand its structure and identify relevant files that allow an assitant to fix the issue with all the context needed?

Follow these steps to resolve the issue:
1. Explore the repository in /testbed to familiarize yourself with its structure.
2. View files to have a complete understanding of the codebase. 
3. Analyze the problem, and identify relevant files and folders.
4. If you've identified, do not stop but continue to explore more files that the fix might impact.
5. Create a script to reproduce the error and execute it with `python <filename.py>` to confirm the error.
6. Analyze more files and create an edge cases script to test the fix.
7. Submit and record useful information to the shared knowledge.

When you are confident that your exploration has enough information and related files to solve the PR, submit the task using the 'submit_with_summary' tool. Follow the format below:
<shared_knowledge_shema>
{shared_knowledge_schema}
</shared_knowledge_schema>

Note that you do not have to fix the issue in this task, focus on gather efficiently information and context.
View a lot of files SIMULTANOUSLY to get a better understanding of the codebase.

You're working autonomously from now on. Your thinking should be thorough, step by step.
"""
                },
                'max_iterations': max_iterations,
                'allowed_tools': ['submit_with_summary', 'create_and_run']
            },
            {
                'name': 'Analysis and Implementation',
                'system_prompt': {
                    "role": "system",
                    "content": "You are a skilled assistant proficient in analyzing code, implementing fix to solve PR while updating other related files to maintain the functionalities of the python open source repository."
                },
                'user_prompt': {
                    "role": "user",
                    "content": """
Consider the shared knowledge collected during exploration and the PR description:
<shared_knowledge>
{shared_knowledge}
</shared_knowledge>

<pr_description>
{problem_statement}
</pr_description>

Can you help me implement the necessary changes to the repository so that the requirements specified in the <pr_description> are met?
I've already taken care of all changes to any of the test files described in the <pr_description>. This means you DON'T have to modify the testing logic or any of the tests in any way!

Your task is to make the minimal changes to non-tests files in the current directory to ensure the <pr_description> is satisfied.

Follow these steps:
1. Run the reproduce_erorr script and test commands listed, to confirm the error.
2. Edit the sourcecode of the repo to resolve the issue
3. Rerun your reproduce script and confirm that the error is fixed!
4. Think about edgecases and make sure your fix handles them as well 

You're working autonomously from now on. Your thinking should be thorough, and so it's fine if it's very long.
"""
                },
                'max_iterations': 30,
                'allowed_tools': ['bash', 'edit_and_run', 'submit_with_summary']
            },
#             {
#                 'name': 'Test and Verification',
#                 'system_prompt': {
#                     "role": "system",
#                     "content": "You are an expert assistant in testing and verifying code changes."
#                 },
#                 'user_prompt': {
#                     "role": "user",
#                     "content": """
# Verify the implemented changes against the requirements:

# <shared_knowledge>
# {shared_knowledge}
# </shared_knowledge>

# <pr_description>
# {problem_statement}
# </pr_description>

# Follow these steps:
# 1. Run tests to verify the changes
# 2. Ensure all existing functionality works
# 3. Submit if all tests pass

# Note that it's possible to make multiple tool calls simultaneously.

# You're working autonomously from now on. Your thinking should be thorough, step by step.
# """
#                 },
#                 'max_iterations': max_iterations,
#                 'allowed_tools': ['bash', 'edit_and_run', 'submit']
#             },
        ]

    task_manager = TaskManager(thread_manager, state_manager, tasks, None)
    await task_manager.run_tasks(thread_id, model_name, problem_statement)

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
