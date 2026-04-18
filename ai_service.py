# ai_service.py - AI question generation using Gemini or OpenAI

import asyncio
import logging
import json
import os
import re

from env_utils import load_env_file

load_env_file()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Configuration — set your API key in .env or
# as an environment variable before running.
#
#   export GEMINI_API_KEY="your-key-here"
#   OR
#   export OPENAI_API_KEY="your-key-here"
#
# The service auto-detects which key is present and tries configured providers
# before failing. It does not synthesize demo questions.
# ─────────────────────────────────────────────

def _gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "")


def _openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "")


def _gemini_model_name() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _openai_model_name() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _build_prompt(topic: str, difficulty: str, num_questions: int, question_type: str) -> str:
    """Build a structured prompt for AI question generation."""

    type_instructions = ""
    if question_type == "mcq":
        type_instructions = (
            "Each question must be multiple-choice with exactly 4 options. "
            "Make the options concise and clearly different from each other. "
            "Provide the correct answer as the full text of the correct option."
        )
        example = '''{
  "question": "What is the capital of France?",
  "type": "mcq",
  "options": ["London", "Berlin", "Paris", "Rome"],
  "correct_answer": "Paris"
}'''
    else:
        type_instructions = (
            "Each question must be a fill-in-the-blank question. "
            "Use '___' as the blank placeholder in the question text. "
            "Provide the correct answer as a short phrase or single word."
        )
        example = '''{
  "question": "The chemical symbol for water is ___.",
  "type": "blank",
  "options": [],
  "correct_answer": "H2O"
}'''

    return f"""You are a professional quiz creator. Generate exactly {num_questions} quiz questions.

Topic: {topic}
Difficulty: {difficulty}
Question Type: {question_type.upper()}

{type_instructions}

Return ONLY a valid JSON array of question objects. No explanation, no markdown, no code blocks.
Each object must have these exact keys: question, type, options, correct_answer.

Example format:
[
  {example}
]

Rules:
- Keep answers unambiguous and factually correct.
- Match the difficulty level.
- For MCQ, make sure the correct answer appears only once among the options.
- For blank questions, keep the answer short.

Generate {num_questions} questions now:"""


def _parse_questions(raw: str, expected_count: int, fallback_type: str) -> list[dict]:
    """Parse and normalize the AI response into the app's expected schema."""
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    raw = re.sub(r"^json\s*", "", raw, flags=re.IGNORECASE).strip()

    questions = json.loads(raw)
    if not isinstance(questions, list):
        raise ValueError("AI response was not a JSON array.")

    normalized: list[dict] = []
    for item in questions[:expected_count]:
        if not isinstance(item, dict):
            continue

        q_type = str(item.get("type", fallback_type)).strip().lower()
        options = item.get("options", [])
        if q_type == "mcq" and not isinstance(options, list):
          options = []
        if q_type != "mcq":
            options = []

        normalized.append({
            "question": str(item.get("question", "")).strip(),
            "type": "mcq" if q_type == "mcq" else "blank",
            "options": [str(option).strip() for option in options][:4],
            "correct_answer": str(item.get("correct_answer", "")).strip(),
        })

    if len(normalized) != expected_count:
        raise ValueError(f"Expected {expected_count} questions, got {len(normalized)}.")

    return normalized


def _should_use_gemini() -> bool:
    return bool(_gemini_api_key())


def _should_use_openai() -> bool:
    return bool(_openai_api_key())


async def generate_questions_gemini(topic: str, difficulty: str, num_questions: int, question_type: str) -> list[dict]:
    """Generate questions using Google Gemini API."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=_gemini_api_key())
        model = genai.GenerativeModel(_gemini_model_name())

        prompt = _build_prompt(topic, difficulty, num_questions, question_type)
        response = await asyncio.to_thread(model.generate_content, prompt)
        raw = response.text.strip()

        questions = _parse_questions(raw, num_questions, question_type)
        logger.info(f"Gemini generated {len(questions)} questions for topic '{topic}'")
        return questions

    except Exception as e:
        logger.error(f"Gemini generation failed: {e}")
        raise


async def generate_questions_openai(topic: str, difficulty: str, num_questions: int, question_type: str) -> list[dict]:
    """Generate questions using OpenAI API."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=_openai_api_key())
        prompt = _build_prompt(topic, difficulty, num_questions, question_type)

        response = await client.chat.completions.create(
            model=_openai_model_name(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )

        raw = response.choices[0].message.content.strip()
        questions = _parse_questions(raw, num_questions, question_type)
        logger.info(f"OpenAI generated {len(questions)} questions for topic '{topic}'")
        return questions

    except Exception as e:
        logger.error(f"OpenAI generation failed: {e}")
        raise


async def generate_questions(topic: str, difficulty: str, num_questions: int, question_type: str) -> list[dict]:
    """
    Main entry point for question generation.
    Tries Gemini first, then OpenAI, then raises if neither succeeds.
    """
    errors: list[str] = []

    if _should_use_gemini():
        try:
            return await generate_questions_gemini(topic, difficulty, num_questions, question_type)
        except Exception as exc:
            errors.append(f"Gemini: {exc}")

    if _should_use_openai():
        try:
            return await generate_questions_openai(topic, difficulty, num_questions, question_type)
        except Exception as exc:
            errors.append(f"OpenAI: {exc}")

    if not errors:
        raise RuntimeError(
            "No AI API key configured. Set GEMINI_API_KEY or OPENAI_API_KEY to generate questions."
        )

    raise RuntimeError("Failed to generate questions with all configured providers: " + " | ".join(errors))


async def evaluate_blank_answer(question_text: str, correct_answer: str, user_answer: str) -> bool:
    """
    Use AI to evaluate fill-in-the-blank answers semantically.
    Falls back to exact/case-insensitive match when no API key is set.
    """
    # Always try simple match first
    if user_answer.strip().lower() == correct_answer.strip().lower():
        return True

    prompt = (
        f"Question: {question_text}\n"
        f"Expected answer: {correct_answer}\n"
        f"Student answer: {user_answer}\n\n"
        "Is the student's answer correct or semantically equivalent to the expected answer? "
        "Reply with only 'yes' or 'no'."
    )

    try:
        if _should_use_gemini():
            import google.generativeai as genai
            genai.configure(api_key=_gemini_api_key())
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            return response.text.strip().lower().startswith("yes")

        elif _should_use_openai():
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=_openai_api_key())
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=5,
            )
            return response.choices[0].message.content.strip().lower().startswith("yes")

    except Exception as e:
        logger.error(f"AI evaluation failed: {e}")

    return False
