import asyncio
import os
import subprocess
import time
from datetime import datetime
from typing import Annotated, Literal, Sequence
from pathlib import Path
import re
import signal

import instructor
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from openai import OpenAI
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any

max_history = 5


def list_checkpoints(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    history = list(orchestrator.get_state_history(config))
    history.reverse()
    return history


top = str((Path(__file__).parent).resolve())
path = os.path.join(top, "DataBase")
load_dotenv(os.path.join(path, ".env"))

explainer_agent_prompt = """
1. To answer a study question, follow this workflow:
   Load_embedding -> Search_material -> Answer.
2. Never answer from your own knowledge if study material is required.
3. If notes are unavailable or embeddings cannot be loaded, stop immediately and apologize that the study material is unavailable.
"""

notes_agent_prompt = """
1. Include every point from the provided PDFs. Do not omit information.
2. Organize notes into topics with concise bullet points.
3. Whenever the PDF provides them, include definitions, advantages, disadvantages, applications, examples, and comparisons.
4. Do not add information that is not supported by the PDFs.
"""

quiz_agent_prompt = """
1. Read the study notes before generating questions.
2. Generate questions only from the provided notes.
3. Do not include question numbers or labels (e.g. Q1, Q-1, Question 1).
4. Each question title must be a single line and contain only the question itself.
5. Do not include hints, numbering, explanations, or formatting in the title.
6. The description may be empty. If used, it may contain multiple lines but must not use Markdown or other formatting.
"""

sub_agent_prompts = {
    "notes": notes_agent_prompt,
    "explainer": explainer_agent_prompt,
    "questions": quiz_agent_prompt,
}


def check_history(history):
    prev = None
    for msg in history:
        if type(msg) is type(prev):
            raise Exception(f"Found {msg} and {prev} to be same instance {type(prev)}")
        prev = msg


def find_directive(state):
    for msg in reversed(state["messages"]):
        if isinstance(msg, AIMessage) and getattr(msg, "name", None) == "Orchestrator":
            return msg.content
    raise ValueError("No orchestrator directive found.")


class SubAgent:
    registry: dict[str, "SubAgent"] = {}

    def __init__(self, name, MCP_name, MCP_port):
        self.name = name
        self.history = []
        self.MCP_name = MCP_name
        self.MCP_port = MCP_port

    async def create(self):
        self.client = MultiServerMCPClient(
            {
                self.MCP_name: {
                    "transport": "sse",
                    "url": f"http://127.0.0.1:{self.MCP_port}/sse",
                }
            }
        )
        tools = await self.client.get_tools()
        api_key = os.getenv("GOOGLE_API_KEY")

        self.llm = ChatGoogleGenerativeAI(
            model="gemma-4-31b-it",
            temperature=0,
            max_tokens=16384 * 8,
            timeout=None,
            max_retries=2,
            google_api_key=api_key,
            streaming=True,
        )

        self.agent = create_agent(
            self.llm, tools, system_prompt=sub_agent_prompts[self.name]
        )

        with open(f"agent_{self.name}.log", "a", encoding="utf-8") as file:
            file.write(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Session Started\n"
            )
        SubAgent.registry[self.name] = self

    def extract_response(self, response):
        for msg in reversed(response["messages"]):
            if isinstance(msg, AIMessage):
                content = msg.content
                if content is None:
                    continue
                if isinstance(content, list):
                    candidates = []
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "thinking":
                                continue
                            if "text" in item:
                                candidates.append(item["text"])
                            elif "content" in item:
                                candidates.append(item["content"])
                        elif isinstance(item, str):
                            candidates.append(item)
                    if candidates:
                        return candidates[-1].strip()
                if isinstance(content, str):
                    return content.strip()
        return ""

    async def query(
        self, query, history: list[BaseMessage], callbacks=None, max_context: int = 5
    ):
        query = "[AI] " + query
        working_history = list(history) + [HumanMessage(content=query)]
        response = await self.agent.ainvoke(
            {"messages": working_history}, config={"callbacks": callbacks}
        )

        text = self.extract_response(response)
        if not text:
            text = "Error: Agent returned an empty or invalid response."

        updated_history = response["messages"]
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(f"agent_{self.name}.log", "a", encoding="utf-8") as file:
            file.write(f"[{current_time}] {response}\n")
        return text, updated_history


def make_agent_node(agent_key: str, node_name: str):
    async def node(state: SuperManagerState, config=None):
        directive = find_directive(state)
        agent = SubAgent.registry[agent_key]

        queue = config["configurable"].get("token_queue") if config else None
        callbacks = [StreamingCallbackHandler(queue, node_name)] if queue else []

        history = state.get("sub_histories", {}).get(agent_key, [])
        response_text, updated_history = await agent.query(
            directive, history, callbacks=callbacks
        )

        return {
            "messages": [AIMessage(content=response_text, name=node_name)],
            "current_worker": node_name,
            "sub_histories": {agent_key: updated_history},
        }

    return node


def merge_sub_histories(current: dict | None, update: dict) -> dict:
    current = dict(current or {})
    current.update(update)
    return current


class SuperManagerState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    current_worker: str
    sub_histories: Annotated[dict[str, list[BaseMessage]], merge_sub_histories]


def trim_sub_histories_node(state: SuperManagerState):
    sub_histories = state.get("sub_histories", {})
    trimmed = {k: v[-max_history:] for k, v in sub_histories.items()}
    return {"sub_histories": trimmed}


class RoutingDirective(BaseModel):
    next_action: Literal[
        "Notes_Agent", "Question_Maker_Agent", "Explainer_Agent", "FINAL_RESPONSE"
    ] = Field(
        description="Choose Notes_Agent or Question_Maker_Agent or Explainer_Agent if their tools are needed. "
        "Choose FINAL_RESPONSE if you are answering the user directly, greeting them, or completing the task."
    )
    response_content: str = Field(
        description="If routing to an agent, write the specific instruction for them. "
        "If FINAL_RESPONSE, write your direct, conversational reply to the human user."
    )


def extract_token_text(token) -> str:
    if isinstance(token, str):
        return token
    elif isinstance(token, dict):
        if "text" in token:
            return str(token["text"])
        elif "content" in token:
            return str(token["content"])
        elif "thinking" in token:
            return f"\n[Thinking: {token['thinking']}]\n"
        return ""
    elif isinstance(token, list):
        parts = []
        for item in token:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                elif "content" in item:
                    parts.append(str(item["content"]))
                elif "thinking" in item:
                    parts.append(f"\n[Thinking: {item['thinking']}]\n")
        return "".join(parts)
    else:
        return str(token)


def get_message_text(content) -> str:
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        candidates = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "thinking":
                    continue
                if "text" in item:
                    candidates.append(item["text"])
                elif "content" in item:
                    candidates.append(item["content"])
            elif isinstance(item, str):
                candidates.append(item)
        if candidates:
            return candidates[-1].strip()
    return str(content)


class StreamingCallbackHandler(AsyncCallbackHandler):
    def __init__(self, queue, agent_name):
        self.queue = queue
        self.agent_name = agent_name
        self.is_thinking = False

    async def on_llm_new_token(self, token, **kwargs) -> None:
        has_thinking = False
        text_content = ""
        thinking_content = ""

        if isinstance(token, str):
            text_content = token
        elif isinstance(token, dict):
            if "thinking" in token:
                has_thinking = True
                thinking_content = str(token["thinking"])
            elif "text" in token:
                text_content = str(token["text"])
            elif "content" in token:
                text_content = str(token["content"])
        elif isinstance(token, list):
            for item in token:
                if isinstance(item, str):
                    text_content += item
                elif isinstance(item, dict):
                    if "thinking" in item:
                        has_thinking = True
                        thinking_content += str(item["thinking"])
                    elif "text" in item:
                        text_content += str(item["text"])
                    elif "content" in item:
                        text_content += str(item["content"])

        if has_thinking:
            if not self.is_thinking:
                self.is_thinking = True
                await self.queue.put(
                    ("token", f"\n[{self.agent_name} Thinking: {thinking_content}")
                )
            else:
                await self.queue.put(("token", thinking_content))
        else:
            if self.is_thinking:
                self.is_thinking = False
                await self.queue.put(("token", f"]\n{text_content}"))
            else:
                if text_content:
                    await self.queue.put(("token", text_content))

    async def on_llm_end(self, response, **kwargs) -> None:
        if self.is_thinking:
            self.is_thinking = False
            await self.queue.put(("token", "]\n"))

    async def on_llm_error(self, error, **kwargs) -> None:
        if self.is_thinking:
            self.is_thinking = False
            await self.queue.put(("token", "]\n"))

    async def on_tool_start(self, serialized: dict, input_str: str, **kwargs) -> None:
        tool_name = serialized.get("name", "tool")
        await self.queue.put(
            ("status", f"\n[{self.agent_name} is running tool: {tool_name}...]\n")
        )

    async def on_tool_end(self, output: str, **kwargs) -> None:
        await self.queue.put(
            ("status", f"\n[{self.agent_name} finished running tool.]\n")
        )


async def notes_maker_node(state: SuperManagerState, config=None):
    super_directive = find_directive(state)

    queue = config["configurable"].get("token_queue") if config else None
    callbacks = []
    if queue:
        callbacks.append(StreamingCallbackHandler(queue, "Notes_Agent"))

    response_text = await notes.query(super_directive, callbacks=callbacks)

    return {
        "messages": [AIMessage(content=response_text, name="Notes_Agent")],
        "current_worker": "Notes_Agent",
    }


async def questions_maker_node(state: SuperManagerState, config=None):
    super_directive = find_directive(state)

    queue = config["configurable"].get("token_queue") if config else None
    callbacks = []
    if queue:
        callbacks.append(StreamingCallbackHandler(queue, "Question_Maker_Agent"))

    response_text = await questions.query(super_directive, callbacks=callbacks)

    return {
        "messages": [AIMessage(content=response_text, name="Question_Maker_Agent")],
        "current_worker": "Question_Maker_Agent",
    }


async def explainer_worker_node(state: SuperManagerState, config=None):
    super_directive = find_directive(state)

    queue = config["configurable"].get("token_queue") if config else None
    callbacks = []
    if queue:
        callbacks.append(StreamingCallbackHandler(queue, "Explainer_Agent"))

    response_text = await explainer.query(super_directive, callbacks=callbacks)

    return {
        "messages": [AIMessage(content=response_text, name="Explainer_Agent")],
        "current_worker": "Explainer_Agent",
    }


async def orchestrator_manager_node(state: SuperManagerState):
    system_prompt = """
You are the Orchestrator Agent.

Your responsibility is to coordinate specialized sub-agents, maintain the complete conversation history, decide the next action, and produce the final response when appropriate.

========================
RESPONSIBILITIES
========================

1. Greeting Handling
- If the user only greets (e.g., "Hi", "Hello", "Hey"), do not invoke any sub-agent.
- Set next_action to "FINAL_RESPONSE".
- Reply with a friendly greeting.

2. Task Analysis and Routing
- Analyze the user's request.
- Decide whether a sub-agent is required.
- If required, send a clear, self-contained instruction to the most appropriate agent:
    • Notes_Agent
    • Question_Maker_Agent
    • Explainer_Agent
- Only involve multiple agents when the task genuinely requires it.

3. Final Response
- When all required sub-tasks have been completed, gather the relevant outputs.
- Set next_action to "FINAL_RESPONSE".
- Present a complete, well-structured response to the user.

4. Explainer Dependency
- Explainer_Agent requires study notes as context.
- If the required notes are unavailable:
    - Do not invoke Explainer_Agent.
    - Inform me that the required notes are missing.
    - Wait for further instructions.

5. Preserve Study Content
- Treat outputs from study-related sub-agents as authoritative.
- Do not rewrite, simplify, summarize, paraphrase, or otherwise modify study content unless explicitly instructed.
- You may improve only non-study conversational text such as introductions, transitions, or conclusions.

========================
COMMUNICATION WITH SUB-AGENTS
========================

You are the direct supervisor of every sub-agent.

- Always communicate directly with the sub-agent.
- Maintain natural conversational continuity whenever appropriate.
- Do not describe the user's request in the third person.
- Give clear, specific, and self-contained instructions whenever important context may be missing.

========================
SUB-AGENT MEMORY
========================

Sub-agents have limited working memory.

- While actively working on a task, a sub-agent retains the conversation history available within its context window.
- After the Orchestrator sends a `FINAL_RESPONSE` to the user, the sub-agent becomes inactive.
- If the user later sends another message and the same sub-agent is invoked again, it may retain only a small amount of recent context from before it became inactive. Do not assume it remembers the entire previous interaction.
- Whenever important information from an earlier interaction is required, include it explicitly in your instruction instead of relying on the sub-agent's memory.

========================
AGENT RESPONSIBILITIES
========================

Notes_Agent
- Create study notes.
- Retrieve study notes.
- Summarize study material.

Question_Maker_Agent
- Generate quizzes.
- Create MCQs.
- Prepare practice questions.

Explainer_Agent
- Explain concepts.
- Answer study-related doubts.
- Clarify study material.
- Requires study notes as input.
- Has notes for itself.

========================
OUTPUT RULES
========================

For every decision, produce:

- next_action
- response_content

Rules:
- If routing to a sub-agent, `response_content` must contain only the instruction for that sub-agent.
- If `next_action` is `FINAL_RESPONSE`, `response_content` must contain only your direct response to the user.
- Never fabricate study content.
- Never modify study content returned by a sub-agent.
- Your role is to coordinate agents, preserve context, and assemble the final response.
"""

    formatted_messages = [{"role": "system", "content": system_prompt}]

    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            formatted_messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            speaker_prefix = (
                f"[{getattr(msg, 'name', 'Agent')}]: "
                if getattr(msg, "name", None)
                else ""
            )
            formatted_messages.append(
                {
                    "role": "user",
                    "content": f"[Non-Human] {speaker_prefix}: {msg.content}",
                }
            )
        elif isinstance(msg, SystemMessage):
            formatted_messages.append({"role": "system", "content": msg.content})

    evaluation = await asyncio.to_thread(
        structured_manager.chat.completions.create,
        model="deepseek/deepseek-v4-flash-0731",
        response_model=RoutingDirective,
        messages=formatted_messages,
        max_tokens=16384 * 4,
        temperature=0,
    )

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if evaluation.next_action == "FINAL_RESPONSE":
        with open("agent_orchestrator.log", "a", encoding="utf-8") as file:
            file.write(
                f"[{current_time}] Response to User: {evaluation.response_content}\n"
            )

        return {
            "current_worker": "FINISH",
            "messages": [
                AIMessage(content=evaluation.response_content, name="Orchestrator")
            ],
        }

    with open("agent_orchestrator.log", "a", encoding="utf-8") as file:
        file.write(
            f"[{current_time}] Routing to: {evaluation.next_action} | Directive: {evaluation.response_content}\n"
        )

    return {
        "current_worker": evaluation.next_action,
        "messages": [
            AIMessage(content=evaluation.response_content, name="Orchestrator")
        ],
    }


def retry_handler(state):
    worker = state["current_worker"]

    return {
        "messages": [
            HumanMessage(content=(f"Invalid worker '{worker}'. Choose a valid one."))
        ]
    }


processes = []


def launch_server(server):
    p = subprocess.Popen(
        server["cmd"],
        cwd=server["cwd"],
        creationflags=(
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        ),
    )
    processes.append(p)


def stop(timeout):
    for p in processes:
        p.terminate()

    for p in processes:
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()


def start():
    SERVERS = [
        {
            "name": "Notes Maker",
            "cwd": os.path.join(top, "NotesMaker"),
            "cmd": [os.path.join(top, ".venv", "Scripts", "python.exe"), "tools.py"],
        },
        {
            "name": "Form Maker",
            "cwd": os.path.join(top, "QuestionMaker"),
            "cmd": [os.path.join(top, ".venv", "Scripts", "python.exe"), "tools.py"],
        },
        {
            "name": "Content Reader",
            "cwd": os.path.join(top, "Explainer"),
            "cmd": [os.path.join(top, ".venv", "Scripts", "python.exe"), "tools.py"],
        },
    ]

    for s in SERVERS:
        launch_server(s)


notes = None
questions = None
explainer = None
structured_manager = None
orchestrator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting MCP Servers")
    start()
    await asyncio.sleep(5)
    print("MCP Servers Started")

    global notes, questions, explainer, structured_manager, orchestrator
    print("Starting Agents")
    notes = SubAgent("notes", "MCP_Notes", "8000")
    await notes.create()

    questions = SubAgent("questions", "MCP_Questions", "8001")
    await questions.create()

    explainer = SubAgent("explainer", "Explainer_And_Doubts_Solver", "8002")
    await explainer.create()

    llm = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    structured_manager = instructor.from_openai(llm, mode=instructor.Mode.MD_JSON)

    builder = StateGraph(SuperManagerState)

    builder.add_node("Trim_Sub_Histories", trim_sub_histories_node)
    builder.add_node("Orchestrator_Manager", orchestrator_manager_node)
    builder.add_node("Notes_Agent", make_agent_node("notes", "Notes_Agent"))
    builder.add_node(
        "Question_Maker_Agent", make_agent_node("questions", "Question_Maker_Agent")
    )
    builder.add_node("Explainer_Agent", make_agent_node("explainer", "Explainer_Agent"))
    builder.add_node("Retry_Handler", retry_handler)

    def routing_edge(state: SuperManagerState):
        worker = state["current_worker"]

        VALID_WORKERS = {
            "Notes_Agent",
            "Question_Maker_Agent",
            "Explainer_Agent",
            "FINISH",
        }

        if worker not in VALID_WORKERS:
            print(f"System: Invalid worker '{worker}'. Choose a valid one.")
            with open("error.log", "a", encoding="utf-8") as file:
                file.write(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] System: Invalid worker '{worker}'. Choose a valid one.\n"
                )
            return "RETRY"

        return worker

    builder.add_conditional_edges(
        "Orchestrator_Manager",
        routing_edge,
        {
            "Notes_Agent": "Notes_Agent",
            "Question_Maker_Agent": "Question_Maker_Agent",
            "Explainer_Agent": "Explainer_Agent",
            "RETRY": "Retry_Handler",
            "FINISH": END,
        },
    )

    builder.add_edge("Retry_Handler", "Orchestrator_Manager")
    builder.add_edge("Notes_Agent", "Orchestrator_Manager")
    builder.add_edge("Question_Maker_Agent", "Orchestrator_Manager")
    builder.add_edge("Explainer_Agent", "Orchestrator_Manager")

    builder.add_edge(START, "Trim_Sub_Histories")
    builder.add_edge("Trim_Sub_Histories", "Orchestrator_Manager")

    orchestrator = builder.compile(checkpointer=MemorySaver())

    with open("agent_orchestrator.log", "a", encoding="utf-8") as file:
        file.write(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Session Started \n"
        )

    print("Agent Started\n")
    yield

    print("Stopping MCP Servers")
    stop(5)
    print("MCP Servers Stopped")


app = FastAPI(title="Pipeline Notes-Quiz API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


class QueryRequest(BaseModel):
    query: str
    thread_id: str = None


@app.post("/chat")
async def chat_endpoint(request: QueryRequest):
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized yet")

    thread_id = request.thread_id
    if not thread_id:
        thread_id = f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    queue = asyncio.Queue()
    config = {
        "configurable": {
            "thread_id": thread_id,
            "token_queue": queue,
        }
    }

    with open("agent_orchestrator.log", "a", encoding="utf-8") as file:
        file.write(
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] HTTP Request -> Orchestrator (thread {thread_id}): {request.query}\n"
        )

    async def run_orchestrator():
        try:
            async for event in orchestrator.astream(
                {"messages": [HumanMessage(content=request.query)]}, config
            ):
                await queue.put(("graph_event", event))
        except Exception as e:
            await queue.put(("error", str(e)))
        finally:
            await queue.put(("done", None))

    async def response_generator():
        task = asyncio.create_task(run_orchestrator())

        try:
            while True:
                msg_type, data = await queue.get()
                if msg_type == "done":
                    break
                elif msg_type == "error":
                    yield f"Error occurred during execution: {data}\n"
                    break
                elif msg_type == "status":
                    print(data, end="")
                    yield data
                elif msg_type == "token":
                    print(data, end="")
                    yield data
                elif msg_type == "graph_event":
                    for node, state in data.items():
                        if "messages" in state and state["messages"]:
                            latest_msg = state["messages"][-1]
                            speaker = (
                                getattr(latest_msg, "name", "Orchestrator")
                                or "Orchestrator"
                            )

                            if node == "Orchestrator_Manager":
                                if state.get("current_worker") == "FINISH":
                                    msg_text = get_message_text(latest_msg.content)
                                    print(f"\nOrchestrator -> You: {msg_text}")
                                    yield f"\nOrchestrator -> You: "
                                    words = re.split(r"(\s+)", msg_text)
                                    for word in words:
                                        if word:
                                            yield word
                                            await asyncio.sleep(0.01)
                                    yield "\n"
                                else:
                                    target = state.get("current_worker", "Worker")
                                    msg_text = get_message_text(latest_msg.content)
                                    msg = f'\nOrchestrator -> {target}: "{msg_text}"\n'
                                    print(msg, end="")
                                    yield msg
                            elif node == "Retry_Handler":
                                msg_text = get_message_text(latest_msg.content)
                                msg = f"\nSystem -> Orchestrator: {msg_text}\n"
                                print(msg, end="")
                                yield msg
                            else:
                                msg = f"\n[{speaker} finished processing.]\n"
                                print(msg, end="")
                                yield msg

                                if node in [
                                    "Notes_Agent",
                                    "Question_Maker_Agent",
                                    "Explainer_Agent",
                                ]:
                                    with open(
                                        "agent_orchestrator.log", "a", encoding="utf-8"
                                    ) as file:
                                        msg_text = get_message_text(latest_msg.content)
                                        file.write(
                                            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {speaker}: {msg_text}\n"
                                        )
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(response_generator(), media_type="text/plain")


@app.get("/checkpoints")
async def get_checkpoints(thread_id: str):
    history = list_checkpoints(thread_id)
    checkpoints = []

    for i, snap in enumerate(history):
        messages = snap.values.get("messages", [])
        has_messages = bool(messages)

        last_msg = messages[-1] if has_messages else None
        last_speaker = getattr(last_msg, "name", None) if last_msg else None
        preview = get_message_text(last_msg.content)[:200] if last_msg else ""

        checkpoints.append(
            {
                "idx": i,
                "current_worker": snap.values.get("current_worker"),
                "next_node": snap.next,
                "last_speaker": last_speaker,
                "preview": preview,
            }
        )

    return checkpoints


@app.post("/retry")
async def retry_endpoint(thread_id: str, idx: int, continue_chat: bool = True):
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized yet")

    history = list_checkpoints(thread_id)
    if idx < 0 or idx >= len(history):
        raise HTTPException(400, "Invalid index")

    target = history[idx]

    fork_config = orchestrator.update_state(target.config, values={})

    if not continue_chat:
        return {
            "status": "forked",
            "messages": [
                get_message_text(m.content) for m in target.values["messages"]
            ],
        }

    queue = asyncio.Queue()
    run_config = {
        **fork_config,
        "configurable": {**fork_config["configurable"], "token_queue": queue},
    }

    async def run_orchestrator():
        try:
            async for event in orchestrator.astream(None, run_config):
                await queue.put(("graph_event", event))
        finally:
            await queue.put(("done", None))

    async def response_generator():
        task = asyncio.create_task(run_orchestrator())

        try:
            while True:
                msg_type, data = await queue.get()

                if msg_type == "done":
                    break
                elif msg_type == "error":
                    yield f"Error occurred during retry: {data}\n"
                    break
                elif msg_type == "status":
                    print(data, end="")
                    yield data
                elif msg_type == "token":
                    print(data, end="")
                    yield data

                elif msg_type == "graph_event":
                    for node, state in data.items():
                        if "messages" not in state or not state["messages"]:
                            continue

                        latest_msg = state["messages"][-1]
                        speaker = (
                            getattr(latest_msg, "name", "Orchestrator")
                            or "Orchestrator"
                        )

                        if node == "Orchestrator_Manager":
                            if state.get("current_worker") == "FINISH":
                                msg_text = get_message_text(latest_msg.content)
                                print(f"\nOrchestrator -> You: {msg_text}")
                                yield "\nOrchestrator -> You: "
                                words = re.split(r"(\s+)", msg_text)

                                for word in words:
                                    if word:
                                        yield word
                                        await asyncio.sleep(0.01)
                                yield "\n"

                            else:
                                target = state.get("current_worker", "Worker")
                                msg_text = get_message_text(latest_msg.content)
                                msg = f'\nOrchestrator -> {target}: "{msg_text}"\n'
                                print(msg, end="")
                                yield msg

                        elif node == "Retry_Handler":
                            msg_text = get_message_text(latest_msg.content)
                            msg = f"\nSystem -> Orchestrator: {msg_text}\n"
                            print(msg, end="")
                            yield msg

                        else:
                            msg = f"\n[{speaker} finished processing.]\n"
                            print(msg, end="")
                            yield msg

                            if node in [
                                "Notes_Agent",
                                "Question_Maker_Agent",
                                "Explainer_Agent",
                            ]:
                                with open(
                                    "agent_orchestrator.log", "a", encoding="utf-8"
                                ) as file:
                                    msg_text = get_message_text(latest_msg.content)
                                    file.write(
                                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {speaker}: {msg_text}\n"
                                    )

        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(response_generator(), media_type="text/plain")


@app.get("/DataBase/form.json")
async def get_quiz_form():
    return FileResponse("DataBase/form.json")


if __name__ == "__main__":
    uvicorn.run("client:app", host="127.0.0.1", port=8080, reload=False)
