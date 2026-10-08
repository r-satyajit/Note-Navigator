from __future__ import annotations

import json
import re
from typing import Any

from langchain_community.vectorstores import FAISS
from langchain_google_genai import ChatGoogleGenerativeAI

from ingestion import source_label


DIFFICULTY_LEVELS = (
    "Beginner",
    "Easy",
    "Intermediate",
    "Advanced",
    "Expert",
)
CHAT_MODEL = "gemini-3.8-flash"


def _response_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("text")
        ]
        if parts:
            return "\n".join(parts).strip()
    return str(content).strip()


def _parse_json(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError("Gemini returned invalid quiz JSON. Please try again.") from error
    if not isinstance(payload, dict):
        raise ValueError("Gemini returned an invalid quiz structure. Please try again.")
    return payload


def _validate_quiz(payload: dict[str, Any], difficulty: str) -> dict[str, Any]:
    questions = payload.get("questions")
    if not isinstance(questions, list) or len(questions) != 5:
        raise ValueError("The quiz must contain exactly five questions. Please try again.")

    validated: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            raise ValueError(f"Question {index} is invalid. Please generate the quiz again.")
        prompt = question.get("question")
        options = question.get("options")
        answer_index = question.get("answer_index")
        explanation = question.get("explanation")
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or not isinstance(options, list)
            or len(options) != 4
            or any(not isinstance(option, str) or not option.strip() for option in options)
            or len({option.strip().casefold() for option in options}) != 4
            or not isinstance(answer_index, int)
            or isinstance(answer_index, bool)
            or not 0 <= answer_index < 4
            or not isinstance(explanation, str)
            or not explanation.strip()
        ):
            raise ValueError(
                f"Question {index} did not meet the four-option quiz format. Please try again."
            )
        validated.append(
            {
                "question": prompt.strip(),
                "options": [option.strip() for option in options],
                "answer_index": answer_index,
                "explanation": explanation.strip(),
            }
        )
    return {"difficulty": difficulty, "questions": validated}


def generate_quiz(
    vector_store: FAISS,
    *,
    difficulty: str,
    api_key: str,
) -> dict[str, Any]:
    if difficulty not in DIFFICULTY_LEVELS:
        raise ValueError("Choose one of the five available difficulty levels.")
    passages = vector_store.similarity_search(
        "Key concepts, definitions, relationships, evidence, and conclusions",
        k=12,
    )
    if not passages:
        raise ValueError("This Space does not contain searchable document passages yet.")

    context = "\n\n---\n\n".join(
        f"[{source_label(document.metadata)}]\n{document.page_content[:1800]}"
        for document in passages
    )
    prompt = f"""Create a source-grounded multiple-choice quiz using only the material below.

Difficulty: {difficulty}
Return exactly five distinct questions. Each question must have exactly four distinct
answer options and one unambiguous correct answer. Match the requested difficulty.
Do not use outside facts. Keep distractors plausible but clearly incorrect according
to the source. Output only valid JSON in this exact shape:
{{
  "questions": [
    {{
      "question": "Question text",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "answer_index": 0,
      "explanation": "Brief source-grounded explanation"
    }}
  ]
}}

Source material:
{context}
"""
    model = ChatGoogleGenerativeAI(
        model=CHAT_MODEL,
        temperature=0.25,
        api_key=api_key,
    )
    response = model.invoke(prompt)
    payload = _parse_json(_response_text(response.content))
    return _validate_quiz(payload, difficulty)
