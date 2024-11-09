import sys
import subprocess
from streamlit.web import cli as stcli
import threading
import signal

class StreamlitRunner:
    def __init__(self):
        self.process = None
        self.thread = None
        self._stop_event = threading.Event()

    def run(self, output_dir):
        def _run():
            sys.argv = ["streamlit", "run", "streamlit_dashboard.py", "--", output_dir]
            stcli.main()

        self.thread = threading.Thread(target=_run)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        if self.thread and self.thread.is_alive():
            # Send SIGTERM to the main process to trigger clean shutdown
            signal.pthread_kill(self.thread.ident, signal.SIGTERM)
            self.thread.join(timeout=5)  # Wait up to 5 seconds for clean shutdown
