"""Generate actual_answers.json using the provided RAG system with a Gemini generator.

``domain_assistant.py`` ships an ``OpenAIGenerator`` that calls the OpenAI
Responses API. Gemini's OpenAI-compatible endpoint only serves
``/chat/completions``, so this runner injects a drop-in ``TextGenerator`` and
reuses the assistant unchanged: same BM25 retriever, same top_k, same grounded
prompt. Only the model transport differs.

Usage:
    python run_rag_gemini.py
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from domain_assistant import generate_actual_answers

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class GeminiGenerator:
    """TextGenerator backed by Gemini's OpenAI-compatible chat endpoint."""

    def __init__(self, max_output_tokens: int = 400, max_retries: int = 3) -> None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("OPENAI_MODEL", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing from .env")
        if not self.model:
            raise RuntimeError("OPENAI_MODEL is missing from .env")
        self.client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries

    def generate(self, prompt: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=self.max_output_tokens,
                )
            except OpenAIError as exc:  # transient rate limits / 5xx
                last_error = exc
                time.sleep(2 * (attempt + 1))
                continue
            answer = (response.choices[0].message.content or "").strip()
            if answer:
                return answer
            last_error = RuntimeError("Gemini returned an empty answer")
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Gemini generation failed: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=Path("data/student_services"))
    parser.add_argument("--dataset", type=Path, default=Path("golden_dataset.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/actual_answers.json"))
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    load_dotenv(Path(__file__).resolve().with_name(".env"))
    args = parse_args()
    try:
        artifact = generate_actual_answers(
            args.dataset,
            args.corpus_dir,
            generator=GeminiGenerator(),
            top_k=args.top_k,
            progress=lambda message: print(message, flush=True),
        )
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, OpenAIError, TypeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"Generated {len(artifact['answers'])} actual answers: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
