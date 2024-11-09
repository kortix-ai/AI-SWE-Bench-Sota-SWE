import sys
import subprocess
import os
import time
import psutil

class StreamlitRunner:
    def __init__(self):
        self.process = None

    def run(self, output_dir):
        # Start Streamlit as a separate process
        cmd = [sys.executable, "-m", "streamlit", "run", "streamlit_dashboard.py", "--", output_dir]
        self.process = subprocess.Popen(cmd)

    def stop(self):
        if self.process:
            try:
                # Get the process group
                parent = psutil.Process(self.process.pid)
                children = parent.children(recursive=True)
                
                # Terminate children first
                for child in children:
                    child.terminate()
                
                # Terminate parent
                parent.terminate()
                
                # Wait for processes to terminate
                gone, alive = psutil.wait_procs(children + [parent], timeout=3)
                
                # Force kill if still alive
                for p in alive:
                    p.kill()
                    
            except psutil.NoSuchProcess:
                pass
            finally:
                self.process = None
