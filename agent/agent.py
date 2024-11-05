import os
import json
import asyncio
from agentpress.thread_manager import ThreadManager
from agentpress.state_manager import StateManager
from agentpress.llm import make_llm_api_call
from tools.files_tool import FilesTool
from tools.terminal_tool import TerminalTool

async def run_agent():
    # Initialize managers and tools
    thread_manager = ThreadManager()
    state_manager = StateManager()

    thread_manager.add_tool(FilesTool)
    thread_manager.add_tool(TerminalTool)

    # Read the instance data
    with open('/swe_util/eval_data/instances/swe-bench-instance.json', 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']
    instance_id = instance_data['instance_id']

    # Initialize the thread
    thread_id = await thread_manager.create_thread()
    await thread_manager.add_message(thread_id, {
        "role": "user",
        "content": problem_statement
    })

    # Define the system prompt
    system_message = {
        "role": "system",
        "content": """
You are a highly skilled software engineer tasked with fixing a bug in the codebase. Follow these instructions:

1. Read the problem statement carefully.
2. Analyze the existing code in the workspace.
3. Apply necessary changes to fix the issue.
4. Ensure your changes adhere to best coding practices.
5. Output the diff of your changes in unified diff format.

Do not include any explanations or comments in your output. Only output the diff.
        """
    }

    # Collect the current code state
    files_tool = FilesTool()
    await files_tool._init_workspace_state()
    workspace_state = await state_manager.get("files")

    # Prepare the user message with the workspace state
    user_message = {
        "role": "user",
        "content": f"""
Problem Statement:
{problem_statement}

Current Codebase:
{json.dumps(workspace_state, indent=2)}
        """
    }

    # LLM parameters
    model_name = "gpt-4"
    temperature = 0.1
    max_tokens = 2048

    # Run the LLM
    messages = [system_message, user_message]
    response = await make_llm_api_call(
        messages=messages,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=os.environ.get("OPENAI_API_KEY")
    )

    # Extract the assistant's reply
    assistant_reply = response['choices'][0]['message']['content']

    # Save the patch to a file
    patch_file = f"/workspace/{instance_id}_patch.diff"
    with open(patch_file, 'w') as f:
        f.write(assistant_reply)

    # Output the results
    output = {
        "instance_id": instance_id,
        "model_patch": assistant_reply,
        "model_name_or_path": model_name
    }
    print(json.dumps(output))

if __name__ == "__main__":
    asyncio.run(run_agent())
