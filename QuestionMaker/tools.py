import asyncio
import json
import logging
import os
from functools import wraps
from pathlib import Path

from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.types import Image
from mcp.server.mcpserver import MCPServer, Context

path = str((Path(__file__).parent / "..").resolve())
path = os.path.join(path, "DataBase")
notes_path = os.path.join(path, "notes.html")
quiz_path = os.path.join(path, "form.json")

req_mcq = 15
req_multi = 3
req_blank = 2

mcp = MCPServer(name="Making_Q_and_A_Form")

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


def create_if_not_exist():
    if not os.path.exists(quiz_path):
        default_json = {
            "mcq": 0,
            "multi_choice": 0,
            "fill_in_blank": 0,
            "next_id": 0,
            "data": [
                {
                    "updateSettings": {
                        "settings": {"quizSettings": {"isQuiz": True}},
                        "updateMask": "quizSettings.isQuiz",
                    }
                }
            ],
        }
        with open(quiz_path, "w") as f:
            json.dump(default_json, f, indent=2)


def save(data):
    with open(quiz_path, "w") as f:
        json.dump(data, f, indent=2)


def load():
    create_if_not_exist()
    with open(quiz_path, "r") as f:
        data = json.load(f)
    return data


@mcp.tool(name="Reads_notes", description="Reads the notes")
@log_tool_call
def Reads_notes() -> str:
    with open(notes_path, "r", encoding="utf-8") as file:
        content = file.read()
    return content


@mcp.tool(
    name="check_remaining",
    description="Returns how many MCQ, multi-choice, and fill-in-the-blank questions can still be added.",
)
@log_tool_call
def check_remaining() -> dict:
    data = load()
    counts = {"mcq": 0, "multi_choice": 0, "fill_in_blank": 0}
    counts["single correct mcq"] = max(0, req_mcq - data["mcq"])
    counts["multi correct mcq"] = max(0, req_multi - data["multi_choice"])
    counts["fill_in_blank"] = max(0, req_blank - data["fill_in_blank"])
    return counts


@mcp.tool(
    name="count_generated",
    description="Counts both past and present questions, unless deleted.",
)
@log_tool_call
def count_generated() -> dict:
    data = load()
    counts = {"mcq": 0, "multi_choice": 0, "fill_in_blank": 0}
    counts["single correct mcq"] = max(0, data["mcq"])
    counts["multi correct mcq"] = max(0, data["multi_choice"])
    counts["fill_in_blank"] = max(0, data["fill_in_blank"])
    return counts


@mcp.tool(
    name="add_mcq",
    description="Adds a multiple choice question with exactly 4 options, one correct answer, and explanations.",
)
@log_tool_call
def add_mcq(
    question_title: str,
    question_description: str,
    options: list[str],
    correct_option_index: int,
    correct_option_explanation: str,
    incorrect_option_explanation: str,
):
    data = load()
    if data["mcq"] > req_mcq - 1:
        return f"More than {req_mcq} MCQs are not allowed."
    if len(options) != 4:
        return "Failed! Options should be of length 4."
    if correct_option_index > 3 or correct_option_index < 0:
        return "Invalid index! It should be 0-3."
    if len(correct_option_explanation) > 600:
        return "Overflow of correct option explanation!!! Size of explanation should be below 600 characters."
    if len(incorrect_option_explanation) > 600:
        return "Overflow of incorrect option explanation!!! Size of explanation should be below 600 characters."
    if len(question_description) > 300:
        return "Overflow of question description!!! Size of question description should be below 300 characters."
    if len(question_title) > 100:
        return "Overflow of question title!!! Size of question title should be below 100 characters."

    values = {
        "createItem": {
            "location": {"index": data["next_id"]},
            "item": {
                "title": question_title,
                "description": question_description,
                "questionItem": {
                    "question": {
                        "required": True,
                        "grading": {
                            "pointValue": 1,
                            "correctAnswers": {
                                "answers": [{"value": options[correct_option_index]}]
                            },
                            "whenRight": {"text": correct_option_explanation},
                            "whenWrong": {"text": incorrect_option_explanation},
                        },
                        "choiceQuestion": {
                            "type": "RADIO",
                            "options": [{"value": option} for option in options],
                        },
                    }
                },
            },
        }
    }
    data["data"].append(values)
    data["mcq"] += 1
    data["next_id"] += 1
    save(data)
    return "MCQ added successfully"


@mcp.tool(
    name="add_multi_choice",
    description="Adds a multi-choice question with 4 options and one or more correct answers.",
)
@log_tool_call
def add_multi_choice(
    question_title: str,
    question_description: str,
    options: list[str],
    correct_options_index: list[int],
    general_explanation: str,
):
    data = load()
    if data["multi_choice"] > req_multi - 1:
        return f"More than {req_multi} multi-choice are not allowed."
    if len(options) != 4:
        return "Failed! Options should be of length 4."
    if len(correct_options_index) < 1:
        return "Invalid count! There should be 1-4 correct options."
    for index in correct_options_index:
        if index > 3 or index < 0:
            return "Invalid index! It should be 0-3."
    if len(general_explanation) > 600:
        return "Overflow of correct option general_explanation!!! Size of general_explanation should be below 600 characters."
    if len(question_description) > 300:
        return "Overflow of question description!!! Size of question description should be below 300 characters."
    if len(question_title) > 100:
        return "Overflow of question title!!! Size of question title should be below 100 characters."

    values = {
        "createItem": {
            "location": {"index": data["next_id"]},
            "item": {
                "title": question_title,
                "description": question_description,
                "questionItem": {
                    "question": {
                        "required": True,
                        "grading": {
                            "pointValue": 1,
                            "correctAnswers": {
                                "answers": [
                                    {"value": options[correct]}
                                    for correct in correct_options_index
                                ]
                            },
                            "whenRight": {"text": general_explanation},
                            "whenWrong": {"text": general_explanation},
                        },
                        "choiceQuestion": {
                            "type": "CHECKBOX",
                            "options": [{"value": option} for option in options],
                        },
                    }
                },
            },
        }
    }
    data["data"].append(values)
    data["multi_choice"] += 1
    data["next_id"] += 1
    save(data)
    return "Multi-choice added successfully"


@mcp.tool(
    name="add_blank",
    description="Adds a fill-in-the-blank question with similar matching correct answer and explanation.",
)
@log_tool_call
def add_blank(
    question_title: str,
    question_description: str,
    answers: list[str],
    general_explanation: str,
):
    data = load()
    if data["fill_in_blank"] > req_blank - 1:
        return f"More than {req_blank} Fill-in Blanks are not allowed."
    if len(general_explanation) > 600:
        return "Overflow of correct option general_explanation!!! Size of general_explanation should be below 600 characters."
    if len(question_description) > 300:
        return "Overflow of question description!!! Size of question description should be below 300 characters."
    if len(question_title) > 100:
        return "Overflow of question title!!! Size of question title should be below 100 characters."
    if len(answers) == 0:
        return "Empty answer not allowed."
    for answer in answers:
        if len(answer) > 50:
            return "Overflow of answer!!! Size of answer should be below 50 characters."

    values = {
        "createItem": {
            "location": {"index": data["next_id"]},
            "item": {
                "title": question_title,
                "description": question_description,
                "questionItem": {
                    "question": {
                        "required": True,
                        "grading": {
                            "pointValue": 1,
                            "correctAnswers": {
                                "answers": [{"value": answer} for answer in answers]
                            },
                            "generalFeedback": {"text": general_explanation},
                        },
                        "textQuestion": {"paragraph": False},
                    }
                },
            },
        }
    }

    data["data"].append(values)
    data["fill_in_blank"] += 1
    data["next_id"] += 1
    save(data)
    return "Fill-in Blank added successfully"


@mcp.tool(
    name="retreive_question",
    description="Retreives saved question that is made now or in past. It may not have access to question that are deleted.",
)
@log_tool_call
def retreive_question(index:int):
    data = load()
    if index < 0:
        return "Invalid negative index"
    if index < len(data["data"]):
        return data["data"][index]
    else:
        return "Index out of range"

if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=8001)
