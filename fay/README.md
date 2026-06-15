# Fay - Multi-Agent Collaboration Workspace

> **Fay** is a premium, local-first multi-agent orchestration platform designed for real-time collaboration. It coordinates a team of 4 specialized AI agents working together to solve code challenges, write software, and run tests locally, powered entirely by offline, zero-cost LLMs.

---

## 🌸 The Concept & Vision

Fay is built on the concept of **synergistic agentic workflows**. Instead of interacting with a single chatbot, Fay sets up a professional software team inside a workspace:

* **Aoi (Project Manager)**: Outlines execution plans, splits requirements into clear tasks, and handles user interactions.
* **Ren (Developer)**: Implements the code using a local LLM, declaring written files in the workspace.
* **Saya (Code Reviewer)**: Performs static review and code verification, providing a verdict badge (`APPROVED` or `REJECTED`).
* **Kaito (QA Tester)**: Formulates test suites and runs commands locally inside the terminal shell.

All of this is presented in a premium **Dark-Mode Glassmorphism Dashboard** featuring a custom high-performance **HTML5 Canvas Particle System** of falling sakura petals and storm rain cycles to merge utility with high-end aesthetic appeal.

---

## 🛠️ Technology Stack

* **Backend Engine**: Python & FastAPI
  - Bi-directional client communication via asynchronous **WebSockets**.
  - Direct integration with local **Ollama** model completions API.
  - Seamless database fetching from the Odysseus SQLite layer.
  - Automated subprocess shell runners with stdout/stderr capture.
  - Intelligent AST & Regex Code Block Parser (`parse_and_write_files`) to extract and write developer-generated code to physical files on the disk.
* **Frontend Design**: Vanilla HTML5, CSS3, and ES6 JavaScript
  - Blur-heavy, frosted-glass components (`backdrop-filter`) with custom neon-glow accents.
  - High-performance, frame-rate matched HTML5 Canvas animation loop.
  - Dynamic channel rooms matching standard collaboration tools (Slack/Discord style).
  - Human-in-the-loop (HITL) prompt gates for command validation.
* **Models Utilized**:
  - `qwen2.5:3b` - Serving PM, Reviewer, and QA roles for low VRAM usage and high speed.
  - `qwen2.5-coder:7b` - Reserved for developer generation tasks.

---

## 🚀 Getting Started

### Prerequisites

Ensure you have **Ollama** installed on your system with the models downloaded:
```powershell
ollama pull qwen2.5:3b
ollama pull qwen2.5-coder:7b
```

### Launching the Workspace

You can launch the Fay server using the custom batch launcher:
1. Double-click the **`run_fay.bat`** file on your Desktop (or run it from the root folder).
2. Open your web browser and navigate to:
   👉 **`http://localhost:8000`**

### Running Claude Code Locally

Fay redirects Claude Code traffic to local models:
1. Run **`run_claude_local.bat`** on your Desktop.
2. It sets up environment variables to intercept Anthropic API traffic and maps it to your local Qwen coder model.

---

## ⚙️ Control Modes

* **Autopilot Mode (ON)**: The agent loop runs automatically from planning to coding, review, and terminal testing execution without interruption.
* **Human-in-the-Loop Mode (OFF)**: If Kaito (Tester) attempts to run any command, the execution queue halts and sends a WebSocket prompt to your dashboard, waiting for you to click **Approve & Run** or **Reject**.
