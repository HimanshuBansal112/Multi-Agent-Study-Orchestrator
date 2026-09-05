# Multi-Agent-Study-Orchestrator

A multi-agent study orchestration platform built with LangGraph, FastAPI, and a premium glassmorphic web interface. It coordinates multiple specialized AI agents (**Notes_Agent**, **Question_Maker_Agent**, and **Explainer_Agent**) through an **Orchestrator** manager to generate study notes, explain concepts, and create interactive quizzes in real time.

---

## Key Features

### 1. Interactive Chat Dashboard (`index.html`)
- **Real-Time Agent Status Tracker**: Sidebar indicators dynamically update (e.g. `running...`) to show which agent is currently executing.
- **Immediate Tool Traces**: Displays completed tool executions (e.g. `Notes_Agent ran tool: Find_materials`) as soon as they finish.
- **Reasoning Process Dropdowns**: Expandable sections reveal each agent's reasoning trace during execution. Only applicable with reasoning supported models.

### 2. State Branching (Retry & Edit)
- **Backward-Scanning Checkpoint Mapping**: Maps chat bubbles to LangGraph checkpoints while correctly handling abandoned execution branches.
- **Prompt Editing**: Edit previous prompts (except the initial message) to roll back to the previous idle checkpoint (`next_node: ["__start__"]`) and create a new conversation branch.
- **Agent & Orchestrator Retry**: Retries execution from the checkpoint immediately before the selected node (e.g. `Orchestrator_Manager`).

### 3. Interactive Quiz Workspace (`quiz.html`)
- **Single-Choice MCQs**: Clickable options with instant correctness validation and visual feedback.
- **Multiple-Choice Questions**: Checkbox-based questions with automatic grading for multiple correct answers.
- **Fill-in-the-Blank Questions**: Case-insensitive and whitespace-trimmed answer validation.
- **Dynamic Explanations**: Displays contextual feedback using `whenRight`, `whenWrong`, and `generalFeedback` responses after submission.

---

## Technology Stack

- **Backend:** Python, FastAPI, FastMCP, LangGraph, Custom RAG, Uvicorn
- **Frontend:** HTML, CSS, JavaScript

---

## Setup & Execution

### 1. Run the Backend Server

Launch the FastAPI application from the project root:

```powershell
.venv\Scripts\python.exe client.py
```

or

```powershell
uv run client.py
```

The server will start at `http://127.0.0.1:8080`.

### 2. Open the Web Interfaces

- **Chat Workspace:** http://127.0.0.1:8080/frontend/index.html
- **Quiz Workspace:** http://127.0.0.1:8080/frontend/quiz.html
