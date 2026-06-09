import os
import sys
import json
import asyncio
import subprocess
import httpx
from typing import List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

# Add workspace root to sys.path so we can import core.database
workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(workspace_dir)

from core.database import SessionLocal, CrewMember

app = FastAPI(title="Fay Agent Platform")

# In-memory storage for chat logs and autopilot settings
chat_logs: List[Dict[str, Any]] = []
autopilot_mode = True  # True = ON, False = OFF

# Websocket manager to broadcast updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# Global variables for human-in-the-loop (HITL) approval
pending_command: Dict[str, Any] = {}
approval_event = asyncio.Event()
approval_decision = False

# Helper to fetch agent profile from database
def get_agent_from_db(agent_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    agent = db.query(CrewMember).filter(CrewMember.id == agent_id).first()
    db.close()
    if agent:
        return {
            "name": agent.name,
            "personality": agent.personality,
            "model": agent.model,
            "greeting": agent.greeting
        }
    return {}

# Call local Ollama API
async def call_ollama(model: str, messages: List[Dict[str, str]]) -> str:
    url = "http://localhost:11434/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.5,
        "stream": False
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            else:
                return f"[Ollama Error: Status {response.status_code}]"
    except Exception as e:
        return f"[Error connecting to Ollama: {str(e)}]"

# Parse Ren's message for FILE declarations or code blocks and write them to disk
def parse_and_write_files(text: str) -> List[str]:
    written_files = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Case 1: Explicit "FILE: filename.ext" prefix
        if line.upper().startswith("FILE:"):
            filename = line[5:].strip().replace("`", "").strip()
            # Find the starting code block
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                i += 1
            if i < len(lines) and lines[i].strip().startswith("```"):
                i += 1
                code_content = []
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_content.append(lines[i])
                    i += 1
                
                file_path = os.path.join(workspace_dir, filename)
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(code_content))
                    written_files.append(filename)
                except Exception as e:
                    print(f"Error writing file {filename}: {e}")
            continue

        # Case 2: Code block without "FILE:" prefix
        if line.startswith("```"):
            lang = line[3:].strip()
            # Extract code block content
            code_start_idx = i
            i += 1
            code_content = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_content.append(lines[i])
                i += 1
            
            if code_content:
                # Check first line for a filename comment (e.g., "# circle_area.py" or "// script.js")
                first_line = code_content[0].strip()
                filename = ""
                
                if first_line.startswith("#"):
                    parts = first_line[1:].strip().split()
                    if parts and ("." in parts[0]):
                        filename = parts[0]
                elif first_line.startswith("//"):
                    parts = first_line[2:].strip().split()
                    if parts and ("." in parts[0]):
                        filename = parts[0]
                elif first_line.startswith("<!--"):
                    content = first_line.replace("<!--", "").replace("-->", "").strip()
                    parts = content.split()
                    if parts and ("." in parts[0]):
                        filename = parts[0]
                
                # Fallback: scan previous lines for a filename
                if not filename:
                    for j in range(max(0, code_start_idx - 3), code_start_idx):
                        words = lines[j].replace("`", " ").replace(":", " ").replace('"', " ").replace("'", " ").split()
                        for w in words:
                            if "." in w and any(w.endswith(ext) for ext in [".py", ".js", ".html", ".css", ".json", ".txt"]):
                                filename = w.strip()
                                break
                        if filename:
                            break
                
                # Ultimate fallback
                if not filename:
                    filename = "script.py" if ("python" in lang or not lang) else f"script.{lang}"
                
                # Clean up path traversal/backticks
                filename = os.path.basename(filename.replace("`", "").strip())
                
                file_path = os.path.join(workspace_dir, filename)
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(code_content))
                    if filename not in written_files:
                        written_files.append(filename)
                except Exception as e:
                    print(f"Error writing file {filename}: {e}")
        i += 1
    return written_files

# Execute a command in workspace
async def execute_command(command: str) -> str:
    try:
        # Run command in workspace directory using powershell/cmd depending on OS
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=workspace_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        return output.strip() if output.strip() else "[Command executed with no output]"
    except Exception as e:
        return f"[Execution Error: {str(e)}]"

# Main multi-agent execution loop
async def run_agent_workflow(user_msg: str):
    global pending_command, approval_decision, approval_event, autopilot_mode
    
    # --- PHASE 1: Project Manager (Aoi) in #general ---
    aoi = get_agent_from_db("fay-pm")
    if not aoi:
        aoi = {"name": "Aoi (Project Manager)", "model": "qwen2.5:3b", "personality": "PM"}
        
    await manager.broadcast({"type": "status", "agent": aoi["name"], "text": "Planning task structure..."})
    
    pm_prompt = (
        f"{aoi['personality']}\n\n"
        f"User request: \"{user_msg}\"\n\n"
        f"Instructions: Create a solid, step-by-step implementation plan. "
        f"Instruct Ren (Developer) on what files to write, and tell the user how we're proceeding."
    )
    
    pm_response = await call_ollama(aoi["model"], [
        {"role": "system", "content": pm_prompt},
        {"role": "user", "content": f"Create plan for: {user_msg}"}
    ])
    
    # Broadcast Aoi's message to #general
    chat_logs.append({"channel": "#general", "sender": aoi["name"], "text": pm_response})
    await manager.broadcast({
        "type": "message",
        "channel": "#general",
        "sender": aoi["name"],
        "text": pm_response
    })
    
    await asyncio.sleep(1.5)

    # --- PHASE 2: Developer (Ren) in #dev ---
    ren = get_agent_from_db("fay-dev")
    if not ren:
        ren = {"name": "Ren (Developer)", "model": "qwen2.5-coder:7b", "personality": "Developer"}
        
    await manager.broadcast({"type": "status", "agent": ren["name"], "text": "Writing code..."})
    
    dev_prompt = (
        f"{ren['personality']}\n\n"
        f"Task details from Project Manager: {pm_response}\n\n"
        f"Instructions: Implement the requested features. Write clean, complete code.\n"
        f"CRITICAL: If you are creating or updating a file, declare it clearly on its own line like:\n"
        f"FILE: filename.py\n"
        f"```python\n"
        f"[your code here]\n"
        f"```\n"
        f"You can create multiple files. Let Saya (Reviewer) know the code is ready for inspection."
    )
    
    dev_response = await call_ollama(ren["model"], [
        {"role": "system", "content": dev_prompt},
        {"role": "user", "content": "Please implement the plan."}
    ])
    
    # Write any files created by Dev
    written_files = parse_and_write_files(dev_response)
    
    # Broadcast Ren's message to #dev
    chat_logs.append({"channel": "#dev", "sender": ren["name"], "text": dev_response})
    await manager.broadcast({
        "type": "message",
        "channel": "#dev",
        "sender": ren["name"],
        "text": dev_response
    })
    
    # Broadcast written file notifications
    for f in written_files:
        notification = f"ℹ️ *System*: File `{f}` has been successfully written/updated in the workspace."
        chat_logs.append({"channel": "#dev", "sender": "System", "text": notification})
        await manager.broadcast({
            "type": "message",
            "channel": "#dev",
            "sender": "System",
            "text": notification
        })
        
    await asyncio.sleep(1.5)

    # --- PHASE 3: Code Reviewer (Saya) in #dev ---
    saya = get_agent_from_db("fay-reviewer")
    if not saya:
        saya = {"name": "Saya (Code Reviewer)", "model": "qwen2.5:3b", "personality": "Reviewer"}
        
    await manager.broadcast({"type": "status", "agent": saya["name"], "text": "Reviewing code..."})
    
    reviewer_prompt = (
        f"{saya['personality']}\n\n"
        f"Here is the developer's output:\n{dev_response}\n\n"
        f"Instructions: Verify the syntax, logic, and structure. Check for any bugs.\n"
        f"End your review with 'APPROVED' if the code is correct and safe to run, "
        f"or 'REJECTED' if it has bugs or needs work."
    )
    
    reviewer_response = await call_ollama(saya["model"], [
        {"role": "system", "content": reviewer_prompt},
        {"role": "user", "content": "Review the code."}
    ])
    
    # Broadcast Saya's message to #dev
    chat_logs.append({"channel": "#dev", "sender": saya["name"], "text": reviewer_response})
    await manager.broadcast({
        "type": "message",
        "channel": "#dev",
        "sender": saya["name"],
        "text": reviewer_response
    })
    
    await asyncio.sleep(1.5)

    # Check approval status
    is_approved = "APPROVED" in reviewer_response.upper()
    
    if not is_approved:
        # If rejected, notify and stop
        failure_msg = "❌ *System*: Code review was rejected. Halting workflow. Developer needs to address reviewer comments."
        chat_logs.append({"channel": "#general", "sender": "System", "text": failure_msg})
        await manager.broadcast({
            "type": "message",
            "channel": "#general",
            "sender": "System",
            "text": failure_msg
        })
        await manager.broadcast({"type": "status", "agent": "", "text": ""})
        return

    # --- PHASE 4: QA Tester (Kaito) in #qa-testing ---
    kaito = get_agent_from_db("fay-tester")
    if not kaito:
        kaito = {"name": "Kaito (QA Tester)", "model": "qwen2.5:3b", "personality": "Tester"}
        
    await manager.broadcast({"type": "status", "agent": kaito["name"], "text": "Formulating test plan..."})
    
    tester_prompt = (
        f"{kaito['personality']}\n\n"
        f"The developer has written code which was APPROVED by Saya.\n"
        f"Written files: {', '.join(written_files) if written_files else 'None'}\n\n"
        f"Instructions: Formulate a test script or command to verify this code.\n"
        f"At the very end of your response, output the exact command to execute in the format:\n"
        f"RUN_COMMAND: <command_here>\n"
        f"For example: RUN_COMMAND: python filename.py"
    )
    
    tester_response = await call_ollama(kaito["model"], [
        {"role": "system", "content": tester_prompt},
        {"role": "user", "content": "Generate testing command."}
    ])
    
    # Broadcast Kaito's response to #qa-testing
    chat_logs.append({"channel": "#qa-testing", "sender": kaito["name"], "text": tester_response})
    await manager.broadcast({
        "type": "message",
        "channel": "#qa-testing",
        "sender": kaito["name"],
        "text": tester_response
    })
    
    # Extract execution command
    cmd_to_run = ""
    for line in tester_response.split("\n"):
        if "RUN_COMMAND:" in line:
            cmd_to_run = line.split("RUN_COMMAND:")[1].strip()
            break
            
    if cmd_to_run:
        cmd_id = f"cmd-{int(asyncio.get_event_loop().time())}"
        
        # Check autopilot setting
        if autopilot_mode:
            # Run automatically
            log_msg = f"⚙️ *System*: Running command on Autopilot: `{cmd_to_run}`"
            chat_logs.append({"channel": "#qa-testing", "sender": "System", "text": log_msg})
            await manager.broadcast({"type": "message", "channel": "#qa-testing", "sender": "System", "text": log_msg})
            
            output = await execute_command(cmd_to_run)
            
            result_msg = f"🖥️ *Terminal Output*:\n```text\n{output}\n```"
            chat_logs.append({"channel": "#qa-testing", "sender": "System", "text": result_msg})
            await manager.broadcast({"type": "message", "channel": "#qa-testing", "sender": "System", "text": result_msg})
        else:
            # Human in the loop approval required
            pending_command = {
                "id": cmd_id,
                "command": cmd_to_run,
                "channel": "#qa-testing"
            }
            approval_event.clear()
            
            # Send approval prompt to frontend
            await manager.broadcast({
                "type": "pending_approval",
                "id": cmd_id,
                "command": cmd_to_run
            })
            
            # Wait for user action
            await approval_event.wait()
            
            if approval_decision:
                log_msg = f"⚙️ *System*: Command APPROVED by User. Running: `{cmd_to_run}`"
                chat_logs.append({"channel": "#qa-testing", "sender": "System", "text": log_msg})
                await manager.broadcast({"type": "message", "channel": "#qa-testing", "sender": "System", "text": log_msg})
                
                output = await execute_command(cmd_to_run)
                
                result_msg = f"🖥️ *Terminal Output*:\n```text\n{output}\n```"
                chat_logs.append({"channel": "#qa-testing", "sender": "System", "text": result_msg})
                await manager.broadcast({"type": "message", "channel": "#qa-testing", "sender": "System", "text": result_msg})
            else:
                log_msg = f"🚫 *System*: Command REJECTED by User. Skipped: `{cmd_to_run}`"
                chat_logs.append({"channel": "#qa-testing", "sender": "System", "text": log_msg})
                await manager.broadcast({"type": "message", "channel": "#qa-testing", "sender": "System", "text": log_msg})
                
            pending_command = {}
            
    await manager.broadcast({"type": "status", "agent": "", "text": ""})

# Static files will be served via app.mount at the bottom


# Websocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global autopilot_mode, approval_decision, approval_event
    await manager.connect(websocket)
    
    # Send all current logs on connection
    for log in chat_logs:
        await manager.send_personal_message({
            "type": "message",
            "channel": log["channel"],
            "sender": log["sender"],
            "text": log["text"]
        }, websocket)
        
    # Send current settings
    await manager.send_personal_message({
        "type": "settings",
        "autopilot": autopilot_mode
    }, websocket)
    
    # If there is a pending command, re-send it
    if pending_command:
        await manager.send_personal_message({
            "type": "pending_approval",
            "id": pending_command["id"],
            "command": pending_command["command"]
        }, websocket)
        
    try:
        while True:
            data = await websocket.receive_text()
            event = json.loads(data)
            
            if event["type"] == "user_message":
                user_text = event["text"]
                channel = event.get("channel", "#general")
                
                # Echo user message
                chat_logs.append({"channel": channel, "sender": "You", "text": user_text})
                await manager.broadcast({
                    "type": "message",
                    "channel": channel,
                    "sender": "You",
                    "text": user_text
                })
                
                # Trigger agents background execution
                asyncio.create_task(run_agent_workflow(user_text))
                
            elif event["type"] == "toggle_autopilot":
                autopilot_mode = event["value"]
                await manager.broadcast({
                    "type": "settings",
                    "autopilot": autopilot_mode
                })
                
            elif event["type"] == "approval_response":
                if pending_command and event.get("id") == pending_command["id"]:
                    approval_decision = event.get("approved", False)
                    approval_event.set()
                    
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Serve the static frontend (including assets/bg.png) at the root level
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Start on port 8000
    uvicorn.run(app, host="127.0.0.1", port=8000)
