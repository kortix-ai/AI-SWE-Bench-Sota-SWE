import json
import asyncio
import argparse
import os
from langfuse.decorators import observe
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
import uuid

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

            await self.thread_manager.add_message(thread_id, {
                "role": "task-switch",
                "content": f"--- Task switched to {task['name']} ---"
            })

            formatted_prompt = {
                "role": task['user_prompt']['role'],
                "content": task['user_prompt']['content'].format(
                    problem_statement=problem_statement
                )
            }
            await self.thread_manager.add_message(thread_id, formatted_prompt)

            shared_knowledge = await self.state_manager.get('shared_knowledge') or {}
            await self.thread_manager.add_message(thread_id, {
                "role": "user",
                "content": f"<shared_knowledge>{json.dumps(shared_knowledge)}</shared_knowledge>"
            })

            allowed_tools = task.get('allowed_tools', [])

            iteration = 0
            while iteration < task['max_iterations']:
                iteration += 1

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
                        if tool_call['function']['name'] == 'submit':
                            print(f"Task '{task['name']}' completed via submit tool, moving to next task...")
                            break

                await self.state_manager.set('shared_knowledge', shared_knowledge)

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
    from tools.shared_knowledge_tool import SharedKnowledgeTool  

    thread_manager.add_tool(RepositoryTools, container_name=container_name, state_file=state_file)
    thread_manager.add_tool(SharedKnowledgeTool, state_file=state_file)  

    tasks = [
        {
            'name': 'Exploration',
            'system_prompt': {
                "role": "system",
                "content": "You are a helpful assistant specialized in exploring code repositories. You can only use the following tools: 'view', 'add_to_shared_knowledge', 'update_shared_knowledge'."
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

Can you help me explore the repository to understand its structure and identify relevant files?

Your task is to make the minimal changes to non-test files in the current directory to ensure the <pr_description> is satisfied.

Follow these steps to resolve the issue:
1. Explore the repository in /testbed to familiarize yourself with its structure.
2. View files to have a complete understanding of the codebase.
3. Identify relevant files and folders.
4. Record useful information to the shared knowledge.

You're working autonomously from now on. Your thinking should be thorough, step by step.

You can use tools to manipulate the shared_knowledge. Use the 'add_to_shared_knowledge' tool to add items, and 'update_shared_knowledge' to update values.

Note that it's possible to make multiple tool calls simultaneously."""
            },
            'allowed_tools': ['view', 'add_to_shared_knowledge', 'update_shared_knowledge'], 
            'max_iterations': max_iterations,
        },
        {
            'name': 'Analysis and Implementation',
            'system_prompt': {
                "role": "system",
                "content": "You are a skilled assistant proficient in analyzing code and implementing solutions. You can only use the following tools: 'replace_string', 'create_and_run', 'add_to_shared_knowledge', 'update_shared_knowledge'."
            },
            'user_prompt': {
                "role": "user",
                "content": """
Consider the shared knowledge collected during exploration and the PR description:
<pr_description>
{problem_statement}
</pr_description>

Your task is to implement the necessary changes to satisfy the requirements.

Follow these steps:
1. Analyze the shared knowledge and requirements
2. Implement the minimal required changes

You're working autonomously from now on. Your thinking should be thorough, step by step.

You can use tools to manipulate the shared_knowledge. Use the 'add_to_shared_knowledge' tool to add items, and 'update_shared_knowledge' to update values.

Note that it's possible to make multiple tool calls simultaneously."""
            },
            'allowed_tools': ['replace_string', 'create_and_run', 'add_to_shared_knowledge', 'update_shared_knowledge'],
            'max_iterations': max_iterations,
        },
        {
            'name': 'Test and Verification',
            'system_prompt': {
                "role": "system",
                "content": "You are an expert assistant in testing and verifying code changes. You can only use the following tools: 'bash', 'add_to_shared_knowledge', 'update_shared_knowledge'."
            },
            'user_prompt': {
                "role": "user",
                "content": """
Verify the implemented changes against the requirements:
<pr_description>
{problem_statement}
</pr_description>

Follow these steps:
1. Run tests to verify the changes
2. Ensure all existing functionality works
3. Submit if all tests pass

You can use tools to manipulate the shared_knowledge. Use the 'add_to_shared_knowledge' tool to add items, and 'update_shared_knowledge' to update values.

Note that it's possible to make multiple tool calls simultaneously.

You're working autonomously from now on. Your thinking should be thorough, step by step.
"""
            },
            'allowed_tools': ['bash', 'add_to_shared_knowledge', 'update_shared_knowledge'],  # Updated line
            'max_iterations': max_iterations,
        },
    ]

    shared_knowledge = {
        'folders_to_explore': [],
        'related_files': [],
        'context_files': [],
        'analysis_codebase': "",
        'pr_analysis': "",
        'reproduce_error_path': "",
        'command_existing_tests': [],
    }

    await state_manager.set('shared_knowledge', shared_knowledge)

    task_manager = TaskManager(thread_manager, state_manager, tasks, shared_knowledge)
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
