import asyncio
import json
import logging
import os
import pickle
from datetime import datetime
from functools import wraps
from pathlib import Path

from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.types import Image
from html_rag import compare, embedding
from mcp.server.mcpserver import MCPServer, Context

path = str((Path(__file__).parent / "..").resolve())
path = os.path.join(path, "DataBase")

notes_path = os.path.join(path, "notes.html")
time_track_path = os.path.join(path, "time_track.json")
embedding_path = os.path.join(path, "embedding.pkl")

mcp = MCPServer(name="Explainer_And_Doubts_Solver")

tool_logger = logging.getLogger("mcp_tools")
tool_logger.setLevel(logging.INFO)

file_handler = logging.FileHandler("fastmcp.log", mode="a", encoding="utf-8")
formatter = logging.Formatter("%(asctime)s [%(levelname)s] - %(message)s")
file_handler.setFormatter(formatter)
tool_logger.addHandler(file_handler)
tool_logger.propagate = False


def log_tool_call(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        tool_name = func.__name__
        clean_inputs = {k: v for k, v in kwargs.items() if not isinstance(v, Context)}

        tool_logger.info(f"START tool={tool_name} | inputs={clean_inputs}")
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            tool_logger.info(f"SUCCESS tool={tool_name} | output={result}")
            return result
        except Exception as e:
            tool_logger.error(f"FAIL tool={tool_name} | error={str(e)}")
            raise e

    return wrapper


def time_embedding_set():
    if os.path.exists(time_track_path):
        with open(time_track_path, "r") as f:
            data = json.load(f)
    else:
        data = {"Notes": None, "Embedding": None}
    local_now = datetime.now().isoformat()
    data["Embedding"] = local_now

    with open(time_track_path, "w") as file:
        json.dump(data, file)


def check_embedding_validity():
    if os.path.exists(time_track_path):
        with open(time_track_path, "r") as f:
            data = json.load(f)
    else:
        data = {"Notes": None, "Embedding": None}

    if data["Notes"] and data["Embedding"]:
        dt1 = datetime.fromisoformat(data["Notes"])
        dt2 = datetime.fromisoformat(data["Embedding"])

        if dt2 > dt1:
            return "Correct"
        else:
            return "Mismatch"
    elif data["Notes"]:
        return "Mismatch"
    else:
        return None


@mcp.tool(
    name="Load_embedding",
    description="Loads embedding. Required to fetch content for evaluation.",
)
@log_tool_call
def Load_embedding():
    global chunks

    integrity = check_embedding_validity()

    if integrity == None:
        return "Cannot do anything until notes are made. Inform user and quit"
    elif integrity == "Mismatch":
        print("Generating Embedding")
        chunks = embedding(notes_path)
        with open(embedding_path, "wb") as f:
            pickle.dump(chunks, f)
        time_embedding_set()
    elif integrity == "Correct":
        with open(embedding_path, "rb") as f:
            chunks = pickle.load(f)
    else:
        raise Exception("Undocumented value found")
    return "Success. Now, you can use Search_material to find answer when needed."


@mcp.tool(
    name="Search_material",
    description="Searches material answering question. Requires Load embedding first.",
)
@log_tool_call
def Search_material(question: str):
    return compare(chunks, question, 5)


if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=8002)
