"""
Gemini LLM Integration — Centralized wrapper for Google Generative AI.

Provides:
  - ``get_gemini_model()``  — configured GenerativeModel singleton
  - ``generate_response()`` — plain-text generation with retry
  - ``generate_structured_response()`` — JSON-mode for structured output

Version: 2026-02-13
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from typing import Any

import google as genai

from backend.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _configure_genai() -> None:
    """Configure the Google GenAI library with the API key."""
    settings = get_settings()
    if not settings.GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Add it to your .env file."
        )
    genai.configure(api_key=settings.GOOGLE_API_KEY)


@lru_cache()
def get_gemini_model(
    model_name: str | None = None,
) -> genai.GenerativeModel:
    """
    Return a cached GenerativeModel instance.

    Args:
        model_name: Override the model. Defaults to settings.LLM_MODEL
                     with the ``gemini/`` prefix stripped (LiteLLM format).
    """
    _configure_genai()
    settings = get_settings()

    name = model_name or settings.LLM_MODEL
    # Strip LiteLLM prefix (e.g. "gemini/gemini-2.5-flash" → "gemini-2.5-flash")
    if name.startswith("gemini/"):
        name = name[len("gemini/"):]

    model = genai.GenerativeModel(name)
    logger.info("Gemini model initialised: %s", name)
    return model


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def generate_response(
    prompt: str,
    system_instruction: str = "",
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    max_retries: int = 2,
) -> str:
    """
    Generate a plain-text response from Gemini.

    Args:
        prompt: The user prompt.
        system_instruction: Optional system-level instruction prepended.
        temperature: Sampling temperature (0.0–2.0).
        max_output_tokens: Maximum response length.
        max_retries: Retries on transient failures.

    Returns:
        The generated text.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    model = get_gemini_model()

    # Build the full prompt with system instruction
    full_prompt = prompt
    if system_instruction:
        full_prompt = f"{system_instruction}\n\n---\n\n{prompt}"

    generation_config = genai.GenerationConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            start = time.perf_counter()
            response = model.generate_content(
                full_prompt,
                generation_config=generation_config,
            )
            elapsed = time.perf_counter() - start
            logger.info("Gemini responded in %.2fs (attempt %d)", elapsed, attempt)

            if response.text:
                return response.text.strip()
            else:
                logger.warning("Gemini returned empty text on attempt %d", attempt)
                last_error = RuntimeError("Empty response from Gemini")

        except Exception as e:
            logger.warning("Gemini call failed (attempt %d/%d): %s", attempt, max_retries, e)
            last_error = e
            if attempt < max_retries:
                time.sleep(1.0 * attempt)  # Simple backoff

    raise RuntimeError(f"Gemini generation failed after {max_retries} attempts: {last_error}")


def generate_structured_response(
    prompt: str,
    response_schema: dict[str, Any],
    system_instruction: str = "",
    temperature: float = 0.3,
    max_retries: int = 2,
) -> dict[str, Any]:
    """
    Generate a structured JSON response from Gemini.

    Uses Gemini's JSON mode (response_mime_type) when available,
    with a fallback to prompt-based JSON extraction.

    Args:
        prompt: The user prompt.
        response_schema: JSON schema describing expected output structure.
        system_instruction: Optional system instruction.
        temperature: Lower for more deterministic structured output.
        max_retries: Retries on failure.

    Returns:
        Parsed JSON dict.

    Raises:
        RuntimeError: If generation or parsing fails.
    """
    model = get_gemini_model()

    schema_str = json.dumps(response_schema, indent=2)
    json_prompt = (
        f"{system_instruction}\n\n" if system_instruction else ""
    ) + (
        f"{prompt}\n\n"
        f"Respond ONLY with a valid JSON object matching this schema:\n"
        f"```json\n{schema_str}\n```\n"
        f"Do not include any text outside the JSON object."
    )

    generation_config = genai.GenerationConfig(
        temperature=temperature,
        max_output_tokens=2048,
        response_mime_type="application/json",
    )

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            start = time.perf_counter()
            response = model.generate_content(
                json_prompt,
                generation_config=generation_config,
            )
            elapsed = time.perf_counter() - start
            logger.info("Gemini JSON response in %.2fs (attempt %d)", elapsed, attempt)

            text = (response.text or "").strip()
            if not text:
                last_error = RuntimeError("Empty JSON response")
                continue

            # Strip markdown code fences if present
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                )

            parsed = json.loads(text)
            return parsed

        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed (attempt %d): %s", attempt, e)
            last_error = e
        except Exception as e:
            logger.warning("Gemini JSON call failed (attempt %d/%d): %s", attempt, max_retries, e)
            last_error = e
            if attempt < max_retries:
                time.sleep(1.0 * attempt)

    raise RuntimeError(f"Structured generation failed after {max_retries} attempts: {last_error}")
