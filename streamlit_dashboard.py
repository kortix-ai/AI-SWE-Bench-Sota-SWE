import streamlit as st
import os
import json
from pathlib import Path
from typing import List, Dict
import re


def parse_tool_result(content):
    try:
        pattern = r'ToolResult\(success=(True|False), output=\'(.*?)\'\)'
        match = re.match(pattern, content, re.DOTALL)
        if match:
            success = match.group(1) == 'True'
            output_str = match.group(2)
            output_unescaped = bytes(output_str, "utf-8").decode("unicode_escape")
            output_json = json.loads(output_unescaped)
            return {
                "success": success,
                "output": output_json.get("output", ""),
                "error": output_json.get("error", ""),
                "exit_code": output_json.get("exit_code", -1)
            }
    except:
        pass
    return {
        "success": True,
        "output": content,
        "error": "",
        "exit_code": 0
    }

def load_evaluation_result(run_dir: str) -> Dict:
    """Load evaluation result JSON for a given run."""
    for file in os.listdir(run_dir):
        if file.endswith('_evaluation_result.json'):
            with open(os.path.join(run_dir, file), 'r') as f:
                return json.load(f)
    return {}

def load_eval_log(run_dir: str) -> str:
    """Load eval log content."""
    for file in os.listdir(run_dir):
        if file.endswith('_eval.log'):
            with open(os.path.join(run_dir, file), 'r') as f:
                return f.read()
    return ""

def load_runs(output_dir: str) -> List[Dict]:
    """Load all runs and their statuses from the output directory."""
    runs = []
    for item in sorted(os.listdir(output_dir)):
        item_path = os.path.join(output_dir, item)
        if os.path.isdir(item_path):
            run_info = {'name': item, 'path': item_path}
            eval_result = load_evaluation_result(item_path)
            # Determine status
            all_tests_passed = False
            if eval_result:
                report = eval_result.get('test_result', {}).get('report', {})
                resolved = report.get('resolved', False)
                all_tests_passed = resolved
                run_info['all_tests_passed'] = all_tests_passed
                run_info['status'] = 'completed'
            else:
                # Evaluation is running
                run_info['all_tests_passed'] = None
                run_info['status'] = 'running'
            runs.append(run_info)
    return runs

def load_thread_data(run_dir: str) -> List[Dict]:
    """Load thread data for a given run."""
    threads_dir = os.path.join(run_dir, 'threads')
    thread_data = []
    if os.path.exists(threads_dir):
        for file in sorted(os.listdir(threads_dir)):
            if file.endswith('.json'):
                try:
                    with open(os.path.join(threads_dir, file), 'r') as f:
                        thread_data.append(json.load(f))
                except json.JSONDecodeError:
                    st.warning(f"Failed to decode JSON from {file}")
    return thread_data

def load_diff_file(run_dir: str, run_name: str) -> str:
    """Load diff file content."""
    diff_file = os.path.join(run_dir, f"{run_name}.diff")
    if os.path.exists(diff_file):
        with open(diff_file, 'r') as f:
            return f.read()
    return ""

def load_log_file(run_dir: str, run_name: str) -> str:
    """Load log file content."""
    log_file = os.path.join(run_dir, f"{run_name}.log")
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            return f.read()
    return ""

def format_message_content(content):
    """Format the message content for display."""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        formatted_content = []
        for item in content:
            if item.get('type') == 'text':
                formatted_content.append(item['text'])
            elif item.get('type') == 'image_url':
                formatted_content.append(f"![Image]({item['url']})")
        return "\n".join(formatted_content)
    return str(content)

def display_run_details(run_data: List[Dict]):
    """Display the details of a selected run."""
    if not run_data:
        st.write("No data available for this run.")
        return

    for thread in run_data:
        messages = thread.get('messages', [])
        for message in messages:
            role = message.get("role", "unknown")
            content = message.get("content", "")
            
            # Assign avatar based on role
            if role == "assistant":
                avatar = "🤖"
            elif role == "user":
                avatar = "👤"
            elif role == "system":
                avatar = "⚙️"
            elif role == "tool":
                avatar = "🔧"
            else:
                avatar = "❓"
            
            with st.chat_message(role, avatar=avatar):
                formatted_content = format_message_content(content)
                if role == "tool":
                    name = message.get("name", "")
                    tool_result = parse_tool_result(content)
                    success = tool_result["success"]
                    output = tool_result["output"]
                    error = tool_result["error"]
                    exit_code = tool_result["exit_code"]
                    
                    icon = "✅" if success else "❌"
                    label = f"{name} {icon}"
                    
                    with st.expander(label=label, expanded=True):
                        st.code(output, language='python')
                        if error:
                            st.error(f"Error: {error}")
                        st.info(f"Exit Code: {exit_code}")
                else:
                    st.markdown(formatted_content)
                
                # Display tool calls if present
                if "tool_calls" in message:
                    st.markdown("**Tool Calls:**")
                    for tool_call in message["tool_calls"]:
                        st.code(
                            f"Function: {tool_call['function']['name']}\n"
                            f"Arguments: {tool_call['function']['arguments']}",
                            language="json"
                        )

def main():
    st.set_page_config(page_title="SWE Bench Real-Time Visualization", layout="wide")

    # Custom style to reduce top margin
    st.markdown(
        """
        <style>
        .appview-container .main .block-container{
            padding-top: 2rem;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Sidebar for output directory and runs
    with st.sidebar:
        st.title("📊 SWE Bench")
# Dashboard
        # st.header("🔍 🔍 Output Directory")
        output_dir = st.text_input(
            "🔍 Output Directory",
            value="./outputs",
            placeholder="/path/to/outputs",
            help="Specify the directory where SWE Bench outputs are stored."
        )

        if not os.path.exists(output_dir):
            st.error(f"🚫 Directory '{output_dir}' does not exist.")
            st.stop()

        st.header("📂 Available Runs")
    runs = load_runs(output_dir)

    if not runs:
        st.sidebar.warning("No runs found in the specified directory.")
        st.stop()

    selected_run = None
    for run in runs:
        run_name = run['name']
        # Modify icon based on status
        if run.get('status') == 'running':
            icon = '⏳'
        elif run.get('all_tests_passed') == True:
            icon = '✅'
        else:
            icon = '❌'
        if st.sidebar.button(f"{icon} {run_name}", key=f"run_{run_name}"):
            selected_run = run_name
            run_dir = run['path']

    st.sidebar.markdown("---")

    # Display run details if a run is selected
    if selected_run:
        st.header(f"📁 Run Details: {selected_run}")
        
        # Create tabs
        tab_names = ["💬 Chat", "📝 Code Diff", "📋 Log", "🔍 Threads", "🧪 Passing Tests", "📄 Eval Logs"]
        current_tab = st.tabs(tab_names)
        
        # Load data based on active tab
        with current_tab[0]:  # Chat tab
            run_data = load_thread_data(run_dir)
            display_run_details(run_data)
            
        with current_tab[1]:  # Diff tab
            diff_content = load_diff_file(run_dir, selected_run)
            if diff_content:
                st.code(diff_content, language="diff")
            else:
                st.info("No diff file available")
                
        with current_tab[2]:  # Log tab
            if st.button("Load Full Log"):
                log_content = load_log_file(run_dir, selected_run)
                if log_content:
                    st.code(log_content, wrap_lines=True)
            else:
                st.info("No log file available")
                
        with current_tab[3]:  # Threads tab
            # if st.button
            run_data = load_thread_data(run_dir)
            if run_data:
                st.json(run_data)
            else:
                st.info("No thread data available")
        
        with current_tab[4]:  # Passing Tests tab
            eval_result = load_evaluation_result(run_dir)
            if eval_result:
                report = eval_result.get('test_result', {}).get('report', {})
                tests_status = report.get('tests_status', {})
                if tests_status:
                    for status_category, tests in tests_status.items():
                        success_tests = tests.get('success', [])
                        failure_tests = tests.get('failure', [])
                        if success_tests:
                            st.subheader(f"{status_category} - Passed Tests")
                            for test in success_tests:
                                st.markdown(f"✅ {test}")
                        if failure_tests:
                            st.subheader(f"{status_category} - Failed Tests")
                            for test in failure_tests:
                                st.markdown(f"❌ {test}")
                else:
                    st.info("No test status available")
            else:
                st.info("No evaluation result available")
        
        with current_tab[5]:  # Eval Logs tab
            eval_log_content = load_eval_log(run_dir)
            if eval_log_content:
                st.code(eval_log_content)
            else:
                st.info("No eval log available")
    else:
        # add space here
        st.markdown("---")

        st.info("👈 Please select a run from the sidebar")

if __name__ == "__main__":
    main()