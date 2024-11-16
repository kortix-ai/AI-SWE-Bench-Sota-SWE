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
    'related_files': [],
    'related_folders': [],
    'pr_description_with_details': "",
    'files_explanations': "",
    'guidance_to_resolve': "",
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
                # Add exploration reminder message
                await self.thread_manager.add_message(thread_id, {
                    "role": task['user_prompt']['role'],
                    "content": task['user_prompt']['content'].format(
                        problem_statement=problem_statement,
                        # shared_knowledge_schema=shared_knowledge_schema
                    )
                })
                await self.thread_manager.run_tool_as_message(
                    thread_id,
                    'view',
                    {'paths': ['/testbed'], 'depth': 1},
                    role='user'
                )
                await self.thread_manager.add_message(thread_id, {
                    "role": "user",
                    "content": f"You have {task['max_iterations']} iterations available for exploration. Use must take the most of of it to explore as many relevant files as possible. The more thorough your exploration, the better the implementation will be. Keep going until I ask you to stop."
                })
            elif task['name'] == 'Analysis and Implementation':
                shared_knowledge = await self.state_manager.get('shared_knowledge') or {}

                await self.thread_manager.add_message(thread_id, {
                    "role": task['user_prompt']['role'],
                    "content": task['user_prompt']['content'].format(
                        problem_statement=problem_statement,
                        shared_knowledge=json.dumps(shared_knowledge)
                    )
                })

                paths = shared_knowledge.get('files_to_edit', []) + shared_knowledge.get('related_files', [])

                await self.thread_manager.add_message_and_run_tool(thread_id, {
                    "role": "assistant",
                    "content": "Let's check the files you've explored so far. Then I'll make analysis and thinking about all the edge cases while making minimal changes when implementing.",
                    "tool_calls": [{
                        "id": str(uuid.uuid4()),
                        "type": "function",
                        "function": {
                            "name": "view",
                            "arguments": json.dumps({"paths": paths})
                        }
                    }]
                })
            else:
                shared_knowledge = await self.state_manager.get('shared_knowledge') or {}

                await self.thread_manager.add_message(thread_id, {
                    "role": task['user_prompt']['role'],
                    "content": task['user_prompt']['content'].format(
                        problem_statement=problem_statement,
                        shared_knowledge=json.dumps(shared_knowledge)
                    )
                })

                paths = shared_knowledge.get('files_to_edit', []) 
                        # shared_knowledge.get('only_important_context_files', [])

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
                            if iteration < task['max_iterations']:
                                await self.thread_manager.add_message(thread_id, {
                                    "role": "user",
                                    "content": f"[Iteration {iteration}/{task['max_iterations']}] You've submitted too early. Please continue to explore or implement."
                                })
                            else:
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

    tasks = [{
    'name': 'Exploration',
    'system_prompt': {
        "role": "system",
        "content": """
        You are an AI assistant specialized in exploring code repositories and preparing tests. Your task is to help developers understand and fix issues in a codebase by thoroughly exploring the repository and gathering relevant information.
        """.strip()
    },
    'user_prompt': {
        "role": "user",
        "content": """

First, let's examine the problem statement:

<problem_statement>
{problem_statement}
</problem_statement>

Now, let's explore the repository located at the following path:

<repository_path>
/testbed/
</repository_path>

Your goal is to explore this repository thoroughly and gather all necessary context to fix the issue described in the problem statement. Follow these steps:

1. Explore the repository structure:
   - Navigate and view directory related to the problem.

2. Investigate important folders:
   - Identify folders that seem relevant to the problem statement.

3. Analyze the problem:
   - Compare the problem statement to the repository structure.
   - Identify potential areas where the issue might be located.

4. Identify relevant files and folders:
   - Based on your analysis, determine which files and folders are most likely to be involved in the fix.

5. Classify files:
   - For each file you examine, classify it as relevant or irrelevant to the issue.
   - Provide a brief explanation for your classification.

6. Continue exploration:
   - Do not stop after identifying a few relevant files.
   - Consider potential side effects or related areas that might be impacted by the fix.

As you gather useful information, record it using the following shared knowledge schema:

Important: Do not submit your findings prematurely. Ensure that you have conducted a thorough exploration of the repository before concluding your task. Your exploration should cover:

- All potentially relevant files and folders
- Possible side effects of the proposed fix
- Any dependencies or related components that might be affected

Only when you are confident that you have gathered comprehensive information and context should you use the 'submit_with_summary' tool.

Remember, your task is to gather information and context, not to fix the issue directly. Provide as much relevant detail as possible to assist the developer in implementing the necessary changes.

You are working autonomously from now on, you must to you at least one tool in the end of your response. IMPORTANT : Make sure to use view MULTIPLE FILES a time to make use of the tool efficiently.
"""
        
#         """
# <uploaded_files>
# /testbed/
# </uploaded_files>
# I've uploaded a Python code repository in the directory /testbed. Consider the following PR description:
# <pr_description>
# {problem_statement}
# </pr_description>

# Can you help me explore the repository to understand its structure and identify relevant files that will allow an assistant to fix the issue with all the necessary context?

# Follow these steps to resolve the issue:
# 1. <simultaneous_actions>Explore the repository in /testbed to familiarize yourself with its structure by viewing all files and directories at once.</simultaneous_actions>
# 2. In important folders, check all the files thoroughly.
# 3. Use <thoughts> tags to document your internal reasoning and insights as you explore.
# 4. Analyze the problem and identify all relevant files and folders.
# 5. After reading a file, classify it as relevant or irrelevant to the issue.
# 6. Do not stop after identifying some files; continue to explore more files that the fix might impact.
# 7. Submit and record useful information to the shared knowledge.

# When you are confident that your exploration has gathered enough information and related files to solve the PR, submit the task using the 'submit_with_summary' tool. Follow the format below:
# <shared_knowledge_schema>
# {shared_knowledge_schema}
# </shared_knowledge_schema>

# Note that you do not have to fix the issue in this task; focus on efficiently gathering information and context.
# You're working autonomously from now on. Your thinking should be thorough and step-by-step.
# """
    },
            'max_iterations': 15,
            'allowed_tools': ['submit_with_summary', 'create_and_run']
        },
        {
            'name': 'Analysis and Implementation',
            'system_prompt': {
                "role": "system",
                "content": "You are a skilled assistant proficient in analyzing code and implementing fixes to solve PRs while updating other related files to maintain the functionalities of the Python open-source repository."
            },
            'user_prompt': {
                "role": "user",
                "content": """
Consider the PR description:

<pr_description>
{problem_statement}
</pr_description>

Can you implement the necessary changes to the repository so that the requirements specified in the <pr_description> are met. Focus on making changes to non-test files in the current directory to ensure the <pr_description> is satisfied.

Follow these steps to resolve the issue:
1. Create a script to reproduce_error.py and execute it to confirm the error.
2. Edit the sourcecode of the repo to resolve the issue
3. Rerun your reproduce script and related existing tests scripts to confirm that the error is fixed and the code base is maintaining it functionalities !
4. Think about edge cases and handle them as well.

Here is what we know so far, if you want to see other files, feel free to use the view tool:
<shared_knowledge>
{shared_knowledge}
</shared_knowledge>

You are working autonomously from now on. Your thinking should be thorough, so it's fine if it's very long.
"""
                },
                'max_iterations': 20,
                'allowed_tools': ['bash', 
                                  'edit_and_run', 
                                #   'create_and_run', 
                                #   'submit_with_summary'
                                'submit'
                                  ]
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
