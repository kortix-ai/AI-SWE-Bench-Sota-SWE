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
            }
    except:
        pass
    return {
        "success": True,
        "output": content,
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
                    
                    icon = "✅" if success else "❌"
                    label = f"{name} {icon}"
                    
                    with st.expander(label=label, expanded=st.session_state.get('expanded_tool', False)):
                        st.code(output, language='python')
                elif role in ["user", "system"]:
                    with st.expander(label=f"{role.title()} Message", expanded=False):
                        st.markdown(formatted_content)
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

def get_chat_content(run_data):
    """Collect the chat content."""
    content = ""
    if not run_data:
        return content
    for thread in run_data:
        messages = thread.get('messages', [])
        for message in messages:
            role = message.get("role", "unknown")
            content_msg = message.get("content", "")
            formatted_content = format_message_content(content_msg)
            content += f"{role.upper()}:\n{formatted_content}\n\n"
    return content

def get_log_content(log_content):
    """Return the log content."""
    return log_content

def get_eval_log_content(eval_log_content):
    """Return the evaluation log content."""
    return eval_log_content

def get_combined_content(run_data, diff_content, eval_log_content, run_dir):
    """Combine Chat, Code Diff, Ground Truth and Eval Logs into a single string."""

    content = "<full-log>\n<agent-reason-execution-process>\n"
    content += get_chat_content(run_data)
    content += "</agent-reason-execution-process>\n\n"
    content += "<eval_logs>\n"
    content += get_eval_log_content(eval_log_content)
    content += "</eval_logs>\n\n"
    
    ground_truth = load_ground_truth(run_dir)
    if ground_truth:
        content += "<ground_truth>\n"
        content += "<correct-patch>\n"
        content += ground_truth.get('patch', '') + "\n"
        content += "</correct-patch>\n"
        content += "<new-test-patch>\n"
        content += ground_truth.get('test_patch', '')
        content += "</new-test-patch>\n"
        content += "</ground_truth>"

    content += "</full-log>"
    return content

def load_ground_truth(run_dir: str) -> Dict:
    """Load ground truth data from json file."""
    for file in os.listdir(run_dir):
        if file.endswith('_ground_truth.json'):
            with open(os.path.join(run_dir, file), 'r') as f:
                return json.load(f)
    return {}

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
            st.warning("No runs found in the specified directory.")
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
            if st.button(f"{icon} {run_name}", key=f"run_{run_name}"):
                selected_run = run_name
                run_dir = run['path']

        st.markdown("---")

        if st.checkbox("Show Log"):
            st.session_state.show_log = True
        else:
            st.session_state.show_log = False
        
        if st.checkbox("Show thread"):
            st.session_state.show_thread = True
        else:
            st.session_state.show_thread = False

        if st.checkbox("Expanded (tool result)"):
            st.session_state.expanded_tool = True
        else:
            st.session_state.expanded_tool = False


    # Display run details if a run is selected
    if selected_run:
        st.header(f"📁 Run Details: {selected_run}")
        
        # Create tabs
        tab_names = ["💬Chat", "📝Code Diff", "💡Ground Truth", "📋 Log", "🔍 Threads", "🧪 Passing Tests", "📄 Eval Logs", "🗄 Combined Logs"]
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
                
        with current_tab[2]:  # Ground Truth tab
            ground_truth = load_ground_truth(run_dir)
            if ground_truth:
                st.subheader("Patch")
                st.code(ground_truth.get('patch', ''), language="diff")
                st.subheader("Test Patch")
                st.code(ground_truth.get('test_patch', ''), language="diff")
            else:
                st.info("No ground truth file available")
                
        with current_tab[3]:  # Log tab
            if st.session_state.show_log:
                log_content = load_log_file(run_dir, selected_run)
                if log_content:
                    st.code(log_content, wrap_lines=True)
                else:
                    st.info("No log file available")
            else:
                st.info("Please check the box to show log")
                
                
        with current_tab[4]:  # Threads tab
            if st.session_state.show_thread:
                thread_data = load_thread_data(run_dir)
                if thread_data:
                    st.json(thread_data)
                else:
                    st.info("No thread data available")
            else:
                st.info("Please check the box to show thread")
            
        with current_tab[5]:  # Passing Tests tab
            eval_result = load_evaluation_result(run_dir)
            if eval_result:
                report = eval_result.get('test_result', {}).get('report', {})
                tests_status = report.get('tests_status', {})
                if tests_status:
                    total_passed = sum(len(tests.get('success', [])) for tests in tests_status.values())
                    total_failed = sum(len(tests.get('failure', [])) for tests in tests_status.values())
                    total_tests = total_failed + total_passed
                    pass_percentage = (total_passed / total_tests) * 100 if total_tests > 0 else 0
                    color = "green" if pass_percentage == 100 else "red"
                    st.markdown(f"<span style='color:{color}; font-size: 20px'>{total_passed} / {total_tests} Tests Passed </span>", unsafe_allow_html=True)
                    for status_category, tests in tests_status.items():
                        failure_tests = tests.get('failure', [])
                        if failure_tests:
                            st.subheader(f"{status_category} - Failed Tests")
                            for test in failure_tests:
                                st.markdown(f"❌ {test}")
                        success_tests = tests.get('success', [])
                        if success_tests:
                            st.subheader(f"{status_category} - Passed Tests")
                            for test in success_tests:
                                st.markdown(f"✅ {test}")
                else:
                    st.info("No test status available")
            else:
                st.info("No evaluation result available")
        
        with current_tab[6]:  # Eval Logs tab
            eval_log_content = load_eval_log(run_dir)
            if eval_log_content:
                st.code(eval_log_content)
            else:
                st.info("No eval log available")

        with current_tab[7]:  # Combined Logs tab
            run_data = load_thread_data(run_dir)
            diff_content = load_diff_file(run_dir, selected_run)
            eval_log_content = load_eval_log(run_dir)
            def get_final_test_log(log_text):
                if not log_text: return log_text
                parts = log_text.split("test process starts")
                return "=================================== test process starts" + parts[-1] if len(parts) > 1 and parts[-1].strip() else log_text
            eval_log_content = get_final_test_log(eval_log_content)
            combined_content = get_combined_content(run_data, diff_content, eval_log_content, run_dir)
            
            if combined_content:
                st.code(combined_content, language="python")
            else:
                st.info("No combined logs available")
    else:
        # add space here
        st.markdown("---")

        st.info("👈 Please select a run from the sidebar")

if __name__ == "__main__":
    main()