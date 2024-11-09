import streamlit as st
import os
import json
from pathlib import Path
from typing import List, Dict
# from streamlit_autorefresh import st_autorefresh

# Constants
# DEFAULT_REFRESH_INTERVAL_MS = 2000  # 2 seconds

def load_runs(output_dir: str) -> List[str]:
    """Load all run directories from the output directory."""
    runs = []
    for item in sorted(os.listdir(output_dir)):
        item_path = os.path.join(output_dir, item)
        if os.path.isdir(item_path):
            runs.append(item)
    return runs

def load_run_data(run_dir: str) -> List[Dict]:
    """Load all thread JSON files for a given run."""
    threads_dir = os.path.join(run_dir, 'threads')
    data = []
    if os.path.exists(threads_dir):
        for file in sorted(os.listdir(threads_dir)):
            if file.endswith('.json'):
                try:
                    with open(os.path.join(threads_dir, file), 'r') as f:
                        thread_data = json.load(f)
                        data.append(thread_data)
                except json.JSONDecodeError:
                    st.warning(f"Failed to decode JSON from {file}")
    return data

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
        # thread_id = thread.get('thread_id', 'Unknown Thread')
        # st.markdown(f"### Thread ID: {thread_id}")
        
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

    # Auto-refresh setup
    # count = st_autorefresh(interval=DEFAULT_REFRESH_INTERVAL_MS, limit=None, key="autorefresh")

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
        run_data = load_run_data(run_dir)
        
        st.header(f"📁 Run Details: {selected_run}")
        display_run_details(run_data)
    else:
        st.info("👈 Please select a run from the sidebar")

if __name__ == "__main__":
    main()
