# SWE Runner: Evaluating AI Agents on SWE-Bench

SWE Runner is a tool for running and evaluating AI agents on the [SWE-Bench](https://github.com/princeton-nlp/SWE-bench) benchmark. It leverages [AgentPress](https://github.com/kortix-ai/agentpress) as the foundational framework for building AI agents.

- **Benchmarking**: Automates the process of running agents on SWE-Bench instances.
- **Agent Integration**: Easily plug in your own AI agent implementations.
- **Dockerized Execution**: Runs each benchmark instance in its own Docker container for isolation.

## Quick Start

1. **Prepare Your Agent**:

   Place your agent implementation in the `agent/` directory. Ensure it includes an `agent.py` script that defines your agent logic.

2. **Run the Benchmark**:

   Execute the `run_benchmark.sh` script to start the benchmarking process.

   ```bash
   bash run_benchmark.sh
   ```

   This script runs `swe_runner.py` with default settings, which processes one example from the SWE-Bench Lite dataset.

3. **Customize Benchmark Settings**:

   You can customize the number of examples, dataset, agent directory, and more by directly running `swe_runner.py` with arguments.

   ```bash
   python swe_runner.py --num-examples 5 --agent-dir ./agent --track-files /tmp/agentpress/ --streamlit
   ```

   - `--num-examples`: Number of examples to test.
   - `--dataset`: Dataset to use (default: `princeton-nlp/SWE-bench_Lite`).
   - `--split`: Dataset split to use (default: `test`).
   - `--agent-dir`: Path to your agent directory.
   - `--output-dir`: Directory to save outputs (default: `./outputs`).
   - `--track-files`: List of files and/or folders to track and copy to outputs directory.
   - `--streamlit`: Launch Streamlit thread viewer after execution.

4. **View Results**:

   After running the benchmark, outputs will be saved in the `outputs/` directory.

   - **Patch Files**: Git diffs of the changes made by the agent for each instance.
   - **Logs**: Execution logs for each instance.
   - **Tracked Files**: If specified, the files and directories tracked during execution.

5. **Visualize Agent Interactions**:

   If you included the `--streamlit` flag, a Streamlit application will launch, allowing you to visualize the agent's conversation threads.

## File Overview

- **run_benchmark.sh**: Shell script to run the benchmarking process with default settings.

- **swe_runner.py**: Main script that handles loading the dataset, running each instance in a Docker container, and collecting outputs.

- **agent/agent.py**: Your agent implementation. Contains the logic for how the agent interacts with the problem instances.

- **agentpress**: Directory containing AgentPress utilities for building AI agents, including:

  - **thread_manager.py**: Manages conversations between the agent and the LLM.
  - **state_manager.py**: Manages the agent's state across iterations.
  - **tools**: Directory for agent tools like `FilesTool` and `TerminalTool`.

- **outputs/**: Directory where outputs from the benchmarking process are saved.

- **agentpress_README.md**: Readme for AgentPress, providing detailed information about its components.

## Customization

- **Using a Different LLM**:

  The agent uses `anthropic/claude-3-5-sonnet-latest` by default. You can change the model in `agent/agent.py` by modifying the `model_name` parameter in the `run_agent` function.

- **Adding Tools**:

  You can add or customize tools available to the agent in `agent/agent.py`. Tools extend the agent's capabilities, such as interacting with files or executing terminal commands.

## Philosophy

- **Modularity**: Designed to be easily customizable and extendable.
- **Isolation**: Each benchmark instance runs in its own Docker container to ensure a clean environment.
- **Transparency**: Outputs and logs are saved for each instance for analysis and debugging.

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests for improvements.

## License

[MIT License](LICENSE)


## Evaluation:

### Install SWE bench
```
git clone https://github.com/princeton-nlp/SWE-bench.git
cd SWE-bench
pip install -e .
```