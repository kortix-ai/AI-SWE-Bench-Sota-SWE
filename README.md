# SWE-Bench Benchmarking Pipeline for Custom Agent Systems

This repository provides a generalized benchmarking pipeline to evaluate custom agent systems using the SWE-Bench benchmark. It allows any agent system to interact with SWE-Bench instances within the existing sandboxed Docker environment, perform actions autonomously (such as editing files, adding new files, and running commands), and produce patches that can be evaluated.

## Table of Contents

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [Prerequisites](#prerequisites)
- [Setup Instructions](#setup-instructions)
- [Running the Benchmark](#running-the-benchmark)
  - [Step 1: Prepare the Agent Code](#step-1-prepare-the-agent-code)
  - [Step 2: Run the Inference Script](#step-2-run-the-inference-script)
  - [Step 3: Evaluate the Generated Patches](#step-3-evaluate-the-generated-patches)
- [Detailed Explanation of Files](#detailed-explanation-of-files)
  - [run_infer.py](#run_inferpy)
  - [scripts/run_benchmark.sh](#scriptsrun_benchmarksh)
  - [agent/](#agent)
- [Customization](#customization)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Overview

This pipeline is designed to be agent-agnostic, allowing you to plug in your custom agent system for evaluation. It consists of the following components:

- **Inference Script (`run_infer.py`)**: Loads the SWE-Bench dataset, prepares the Docker environment, runs the agent inside the container, and collects outputs.
- **Agent System (`agent/` directory)**: Your custom agent system code.
- **Evaluation Scripts**: Provided by the SWE-Bench benchmark to evaluate the generated patches.

## Directory Structure

```
.
├── agent/                  # Your custom agent system code
├── run_infer.py            # Inference script to run the agent on SWE-Bench instances
├── scripts/
│   └── run_benchmark.sh    # Helper script to run the entire benchmark
├── outputs/                # Directory where outputs will be saved
└── README.md               # This README file
```

## Prerequisites

- **Docker**: Ensure Docker is installed and running on your system.
- **Python 3.8+**: Required to run the inference script.
- **SWE-Bench Dataset**: The script will automatically download the dataset from Hugging Face Datasets.

## Setup Instructions

1. **Clone this repository**:

   ```bash
   git clone https://github.com/your_username/swe-bench-custom-agent.git
   cd swe-bench-custom-agent
   ```

2. **Place your agent code in the `agent/` directory**:

   - Copy your agent system code (which can be a whole folder) into the `agent/` directory.
   - Ensure that the main script of your agent is named `agent.py` or adjust the `run_infer.py` accordingly.

3. **Set up environment variables** (if needed):

   - If your agent requires API keys (e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), export them in your environment:

     ```bash
     export OPENAI_API_KEY=your_openai_api_key
     export ANTHROPIC_API_KEY=your_anthropic_api_key
     ```

## Running the Benchmark

### Step 1: Prepare the Agent Code

Ensure your agent code is ready to be executed within the SWE-Bench Docker environment:

- **Dependencies**: List all your agent's Python dependencies in a `requirements.txt` file inside the `agent/` directory.
- **Adjust File Paths**: Ensure that any file paths in your agent code are relative and compatible with the Docker environment.
- **Environment Variables**: Your agent should read API keys and other configurations from environment variables.

### Step 2: Run the Inference Script

Run the `run_infer.py` script to execute your agent on the SWE-Bench instances:

```bash
python run_infer.py --num-examples 5 --agent-dir ./agent
```

- `--num-examples`: Number of SWE-Bench instances to process.
- `--agent-dir`: Path to your agent directory.

The script will:

- Load the specified number of instances from the SWE-Bench dataset.
- For each instance:
  - Prepare the SWE-Bench Docker environment.
  - Copy your agent code into the Docker container.
  - Run your agent within the Docker container, allowing it to interact with the SWE-Bench instance directly.
  - Collect and save the agent's output (e.g., generated patches) in the `outputs/` directory.

### Step 3: Evaluate the Generated Patches

After running the inference script, you can evaluate the generated patches using the SWE-Bench evaluation scripts.

1. **Install SWE-Bench Evaluation Tools**:

   - Follow the instructions on the SWE-Bench GitHub repository to install the evaluation tools.

2. **Run the Evaluation Script**:

   ```bash
   # Assuming you have an evaluation script named eval_infer.sh
   ./evaluation/swe_bench/scripts/eval_infer.sh outputs/output.jsonl
   ```

   Replace `outputs/output.jsonl` with the path to your output file.

## Detailed Explanation of Files

### run_infer.py

This is the main inference script that orchestrates the benchmarking process.

```python
import os
import json
import subprocess
import argparse
import tempfile
from datasets import load_dataset

def get_instance_docker_image(instance_id: str) -> str:
    """Get the docker image name for a specific instance."""
    DOCKER_IMAGE_PREFIX = os.environ.get('EVAL_DOCKER_IMAGE_PREFIX', 
     'docker.io/xingyaoww/')
    image_name = 'sweb.eval.x86_64.' + instance_id
    image_name = image_name.replace('__', '_s_')  # To comply with Docker naming conventions
    return (DOCKER_IMAGE_PREFIX.rstrip('/') + '/' + image_name).lower()

def get_swebench_workspace_dir_name(instance: dict) -> str:
    """Get the properly formatted workspace directory name."""
    return f"{instance['repo']}__{instance['version']}".replace('/', '__')

def process_instance(instance: dict, agent_dir: str, output_dir: str):
    instance_id = instance['instance_id']
    print(f"Processing instance: {instance_id}")
    workspace_dir_name = get_swebench_workspace_dir_name(instance)

    # Get the Docker image for this instance
    docker_image = get_instance_docker_image(instance_id)
    print(f"Using Docker image: {docker_image}")

    # Pull the Docker image
    print("Pulling Docker image...")
    subprocess.run(['docker', 'pull', docker_image], check=True)

    # Prepare temporary directory to store instance data
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save instance data
        instance_file = os.path.join(temp_dir, 'swe-bench-instance.json')
        with open(instance_file, 'w') as f:
            json.dump([instance], f)

        # Run agent inside Docker
        cmd = [
            'docker', 'run', '--rm',
            '-v', f'{agent_dir}:/agent',  # Mount agent code
            '-v', f'{temp_dir}:/swe_util/eval_data/instances',  # Mount instance data
            '-e', f'SWE_INSTANCE_ID={instance_id}',
            '-e', f'OPENAI_API_KEY={os.environ.get("OPENAI_API_KEY", "")}',
            '-e', f'ANTHROPIC_API_KEY={os.environ.get("ANTHROPIC_API_KEY", "")}',
            docker_image,
            '/bin/bash', '-c',
            'source /swe_util/instance_swe_entry.sh && cd /workspace && python /agent/agent.py'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error running agent for instance {instance_id}: {result.stderr}")
        else:
            print(f"Agent output for instance {instance_id}:\n{result.stdout}")
            # Save the agent's output
            output_file = os.path.join(output_dir, f'{instance_id}.json')
            with open(output_file, 'w') as f:
                f.write(result.stdout)

def main():
    parser = argparse.ArgumentParser(description="Run SWE-Bench tests with a custom agent.")
    parser.add_argument("--num-examples", type=int, default=1,
                        help="Number of examples to test (default: 1)")
    parser.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite",
                        help="Dataset to use (default: princeton-nlp/SWE-bench_Lite)")
    parser.add_argument("--split", default="test",
                        help="Dataset split to use (default: test)")
    parser.add_argument("--agent-dir", required=True,
                        help="Path to your agent directory")
    parser.add_argument("--output-dir", default="./outputs",
                        help="Directory to save outputs (default: ./outputs)")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # Load dataset
    dataset = load_dataset(args.dataset, split=args.split)

    # Get the first N instances
    instances = dataset.select(range(min(args.num_examples, len(dataset))))

    # Process each instance
    for instance in instances:
        process_instance(instance, args.agent_dir, args.output_dir)

if __name__ == "__main__":
    main()
```

**Key Points**:

- The script loads the dataset and processes each instance individually.
- For each instance:
  - It pulls the corresponding SWE-Bench Docker image.
  - It runs your agent inside the Docker container, mounting your agent code and the instance data.
  - It sets the necessary environment variables.
  - It sources the `instance_swe_entry.sh` script to prepare the environment.
- The agent's output is saved in the `outputs/` directory.

### scripts/run_benchmark.sh

A helper script to automate the benchmarking process.

```bash
#!/bin/bash

# Run the inference script
python run_infer.py --num-examples 5 --agent-dir ./agent

# Run the evaluation (assuming you have the evaluation script set up)
# ./evaluation/swe_bench/scripts/eval_infer.sh outputs/output.jsonl
```

### agent/

This directory contains your agent system code. Ensure that:

- `agent.py`: The main script that runs your agent.
- `requirements.txt`: List all the Python dependencies your agent requires.
- Any additional files or modules are included in this directory.

### agent/agent.py

Here's an example of how you might adjust your `agent.py` to work within the SWE-Bench Docker environment:

```python
import os
import json
import asyncio
from agentpress.thread_manager import ThreadManager
from tools.files_tool import FilesTool
from agentpress.state_manager import StateManager
from tools.terminal_tool import TerminalTool

async def run_agent():
    # Initialize managers and tools
    thread_manager = ThreadManager()
    state_manager = StateManager()

    thread_manager.add_tool(FilesTool)
    thread_manager.add_tool(TerminalTool)

    # Read the problem statement from the instance data
    with open('/swe_util/eval_data/instances/swe-bench-instance.json', 'r') as f:
        instance_data = json.load(f)[0]
    problem_statement = instance_data['problem_statement']

    # Initialize the thread
    thread_id = await thread_manager.create_thread()
    await thread_manager.add_message(thread_id, {
        "role": "user",
        "content": problem_statement
    })

    # Run your agent logic here
    # For example, the rest of your code from agent.py

    # ... (Your agent's logic)

    # Output the results
    # For SWE-Bench evaluation, you might need to output a JSON with 'instance_id' and 'model_patch'
    # For example:
    output = {
        "instance_id": instance_data['instance_id'],
        "model_patch": "Your generated patch here",
        "model_name_or_path": "YourAgentName"
    }
    print(json.dumps(output))

if __name__ == "__main__":
    asyncio.run(run_agent())
```

**Notes**:

- The agent reads the instance data from `/swe_util/eval_data/instances/swe-bench-instance.json`.
- The agent operates within the Docker container's environment, allowing it to interact with the SWE-Bench instance.
- At the end, the agent outputs the results in JSON format, which is captured by the `run_infer.py` script.

## Customization

- **Changing the Number of Examples**: Adjust the `--num-examples` argument when running `run_infer.py`.
- **Using a Different Dataset**: Use the `--dataset` and `--split` arguments to specify a different dataset or split.
- **Adjusting Agent Code**: Modify your agent code within the `agent/` directory as needed.

## Troubleshooting

- **Docker Pull Issues**: Ensure you have access to the SWE-Bench Docker images. If needed, log in to the Docker registry or update the `DOCKER_IMAGE_PREFIX` to point to the correct location.
- **Agent Errors**: Check the agent's output logs for any errors. Ensure that the agent code is compatible with the environment inside the Docker container.
- **API Keys**: Ensure that any required API keys are correctly passed into the Docker container via environment variables.

## License

This project is licensed under the MIT License.

