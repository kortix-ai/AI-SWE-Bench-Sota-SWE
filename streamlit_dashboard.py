import streamlit as st
import os
import json
from pathlib import Path
from typing import List, Dict
from streamlit_autorefresh import st_autorefresh

# Constants
DEFAULT_REFRESH_INTERVAL_MS = 10000  # 10 seconds

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
        thread_id = thread.get('thread_id', 'Unknown Thread')
        with st.expander(f"🔄 Thread ID: {thread_id}", expanded=True):
            messages = thread.get('messages', [])
            for message in messages:
                role = message.get("role", "unknown")
                content = message.get("content", "")
                formatted_content = format_message_content(content)

                # Assign an emoji based on the role
                if role == "assistant":
                    avatar = "🤖 Assistant"
                elif role == "user":
                    avatar = "👤 User"
                elif role == "system":
                    avatar = "⚙️ System"
                elif role == "tool":
                    avatar = "🛠️ Tool"
                else:
                    avatar = f"❓ {role.capitalize()}"

                st.markdown(f"**{avatar}:** {formatted_content}")

                # Display tool calls if present
                if "tool_calls" in message:
                    st.markdown("**🔧 Tool Calls:**")
                    for tool_call in message["tool_calls"]:
                        st.code(json.dumps(tool_call, indent=2), language="json")

def main():
    st.set_page_config(page_title="SWE Bench Real-Time Visualization", layout="wide")
    st.title("📊 SWE Bench Real-Time Visualization")

    # Auto-refresh setup
    count = st_autorefresh(interval=DEFAULT_REFRESH_INTERVAL_MS, limit=None, key="autorefresh")

    # Input for output directory
    output_dir = st.text_input(
        "🔍 Enter Output Directory",
        value="./outputs",
        placeholder="/path/to/outputs",
        help="Specify the directory where SWE Bench outputs are stored."
    )

    if not os.path.exists(output_dir):
        st.error(f"🚫 Output directory '{output_dir}' does not exist.")
        st.stop()

    # Sidebar for selecting runs
    st.sidebar.header("📂 Available Runs")
    runs = load_runs(output_dir)

    if not runs:
        st.sidebar.warning("No runs found in the specified directory.")
        st.stop()

    selected_run = st.sidebar.selectbox("📝 Select a Run", runs)
    run_dir = os.path.join(output_dir, selected_run)

    st.sidebar.markdown("---")
    refresh_interval = st.sidebar.slider(
        "🔄 Refresh Interval (seconds)",
        min_value=5,
        max_value=60,
        value=10,
        help="Set the interval for refreshing the run data."
    )

    # Update the autorefresh interval if changed
    if refresh_interval * 1000 != DEFAULT_REFRESH_INTERVAL_MS:
        st_autorefresh(interval=refresh_interval * 1000, limit=None, key="autorefresh")

    # Placeholder for run details
    run_details_placeholder = st.empty()

    # Load and display run data
    run_data = load_run_data(run_dir)

    with run_details_placeholder.container():
        st.header(f"📁 Run Details: {selected_run}")
        display_run_details(run_data)

if __name__ == "__main__":
    main()
