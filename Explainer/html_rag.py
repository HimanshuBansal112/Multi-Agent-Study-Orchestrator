import os
import re
import time
from pathlib import Path

import numpy as np
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from markdownify import markdownify

path = str((Path(__file__).parent / "..").resolve())
path = os.path.join(path, "DataBase")
load_dotenv(os.path.join(path, ".env"))

api_key = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key)


class ScientificHTMLExtractor:
    def __init__(self):
        self.eq_counter = 1

    def extract(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for script in soup.find_all("script", type=re.compile(r"math/tex")):
            latex = script.get_text(strip=True)

            replacement = f"\n<EQUATION_{self.eq_counter}>\n$$\n{latex}\n$$\n"

            script.replace_with(soup.new_string(replacement))

            self.eq_counter += 1

        for ann in soup.find_all("annotation", {"encoding": "application/x-tex"}):
            latex = ann.get_text(strip=True)

            replacement = f"\n<EQUATION_{self.eq_counter}>\n$$\n{latex}\n$$\n"

            if ann.parent:
                ann.parent.replace_with(soup.new_string(replacement))

            self.eq_counter += 1

        for math in soup.find_all("math"):
            replacement = f"\n<MATHML_{self.eq_counter}>\n{str(math)}\n"

            math.replace_with(soup.new_string(replacement))

            self.eq_counter += 1

        for sup in soup.find_all("sup"):
            sup.replace_with(f"^({sup.get_text(strip=True)})")

        for sub in soup.find_all("sub"):
            sub.replace_with(f"_({sub.get_text(strip=True)})")

        for tag in soup.find_all(["style", "noscript", "iframe", "canvas"]):
            tag.decompose()

        for script in soup.find_all("script"):
            script.decompose()

        markdown = markdownify(str(soup), heading_style="ATX")

        markdown = re.sub(r"\n{3,}", "\n\n", markdown)

        markdown = re.sub(r"[ \t]+", " ", markdown)

        return markdown.strip()


def chunk_by_headings(markdown):
    chunks = []
    current_heading = None
    current_text = []
    for line in markdown.splitlines():
        if re.match(r"^#{1,6}\s", line):
            if current_text:
                chunks.append(
                    {"section": current_heading, "text": "\n".join(current_text)}
                )
            current_heading = line
            current_text = [line]
        else:
            current_text.append(line)
    if current_text:
        chunks.append({"section": current_heading, "text": "\n".join(current_text)})
    return chunks


def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)

    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def embedding(notes_path):
    with open(notes_path, encoding="utf-8") as f:
        html = f.read()

    extractor = ScientificHTMLExtractor()
    markdown_text = extractor.extract(html)
    chunks = chunk_by_headings(markdown_text)

    for chunk in chunks:
        max_attempts = 3
        attempt = 1
        success = False

        while attempt <= max_attempts and not success:
            try:
                response = client.models.embed_content(
                    model="gemini-embedding-2", contents=chunk["text"]
                )
                chunk["embedding"] = response.embeddings[0].values
                success = True

            except Exception as e:
                print(f"Attempt {attempt} failed for chunk: {e}")

                if attempt == 1:
                    print("Retrying (Attempt 2)...")
                    attempt += 1
                elif attempt == 2:
                    print("Waiting 1.5 minutes before Attempt 3...")
                    time.sleep(90)
                    attempt += 1
                else:
                    print("Attempt 3 failed. Skipping chunk or raising exception.")
                    raise e
    return chunks


def compare(chunks, query, k):
    query_embedding = (
        client.models.embed_content(model="gemini-embedding-2", contents=query)
        .embeddings[0]
        .values
    )

    scores = []

    for chunk in chunks:
        score = cosine_similarity(query_embedding, chunk["embedding"])

        scores.append((score, chunk))

    scores.sort(reverse=True, key=lambda x: x[0])

    top_chunks = [chunk for _, chunk in scores[:k]]

    context = "\n\n".join(f"Section: {c['section']}\n{c['text']}" for c in top_chunks)

    prompt = f"""Context:
{context}

Question:
{query}
"""
    return prompt
