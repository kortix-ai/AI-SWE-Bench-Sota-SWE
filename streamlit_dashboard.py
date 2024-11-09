import streamlit as st
import os
import json
from pathlib import Path
from typing import List, Dict


def load_runs(output_dir: str) -> List[str]:
    """Load all run directories from the output directory."""
    runs = []
    for item in sorted(os.listdir(output_dir)):
        item_path = os.path.join(output_dir, item)
        if os.path.isdir(item_path):
            runs.append(item)
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
    run_name = run_dir.split('_', 1)[1] if '_' in run_name else run_name
    diff_file = os.path.join(run_dir, f"{run_name}.diff")
    if os.path.exists(diff_file):
        with open(diff_file, 'r') as f:
            return f.read()
    return ""

def load_log_file(run_dir: str, run_name: str) -> str:
    """Load log file content."""
    run_name = run_dir.split('_', 1)[1] if '_' in run_name else run_name
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
    st.title("📊 SWE Bench Dashboard")

    # Sidebar for output directory and runs
    with st.sidebar:
        st.header("🔍 Output Directory")
        output_dir = st.text_input(
            "Enter path",
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

    # Create buttons for each run
    selected_run = None
    for run in runs:
        if st.sidebar.button(f"📝 {run}", key=f"run_{run}"):
            selected_run = run

    st.sidebar.markdown("---")

    # Display run details if a run is selected
    if selected_run:
        run_dir = os.path.join(output_dir, selected_run)
        
        st.header(f"📁 Run Details: {selected_run}")
        
        # Create tabs
        tab_names = ["💬 Chat", "📝 Code Diff", "📋 Log", "🔍 Threads"]
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
            log_content = load_log_file(run_dir, selected_run)
            if log_content:
                st.code(log_content)
            else:
                st.info("No log file available")
                
        with current_tab[3]:  # Threads tab
            run_data = load_thread_data(run_dir)
            if run_data:
                st.json(run_data)
            else:
                st.info("No thread data available")
    else:
        st.info("👈 Please select a run from the sidebar")

if __name__ == "__main__":
    main()
