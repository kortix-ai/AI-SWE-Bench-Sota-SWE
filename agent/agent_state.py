import asyncio
import json
import os

class AgentState:
    def __init__(self, state_file: str):
        self.state_file = state_file
        self.state = {
            "changed_files": {},
            "logs": []
        }
        self.lock = asyncio.Lock()
    
    async def load_state(self):
        async with self.lock:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    self.state = json.load(f)
            else:
                await self.save_state()
    
    async def save_state(self):
        async with self.lock:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
    
    async def add_changed_file(self, file_path: str, changes: str):
        self.state["changed_files"][file_path] = changes
        await self.save_state()
    
    async def get_changed_files(self):
        return self.state.get("changed_files", {})
    
    async def add_log(self, log_entry: str):
        self.state["logs"].append(log_entry)
        await self.save_state()
    
    async def get_logs(self):
        return self.state.get("logs", [])
    
    async def reset_state(self):
        self.state = {
            "changed_files": {},
            "logs": []
        }
        await self.save_state()
