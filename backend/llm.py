"""
Gemini LLM Integration — Centralized wrapper for Google Generative AI using LangChain.

Provides:
  - ``get_gemini_model()``  — configured ChatGoogleGenerativeAI instance
  - ``generate_response()`` — plain-text generation with retry
  - ``generate_structured_response()`` — JSON-mode for structured output

Version: 2026-03-27
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from typing import Any
from langsmith import traceable

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from backend.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@lru_cache()
def get_gemini_model(
    model_name: str | None = None,
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
) -> ChatGoogleGenerativeAI:
    """
    Return a cached ChatGoogleGenerativeAI instance.

    Args:
        model_name: Override the model. Defaults to settings.LLM_MODEL
                     with the ``gemini/`` prefix stripped (LiteLLM format).
    """
    settings = get_settings()

    if not settings.GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Add it to your .env file."
        )

    name = model_name or settings.LLM_MODEL
    # Strip LiteLLM prefix (e.g. "gemini/gemini-2.5-flash" -> "gemini-2.5-flash")
    if name.startswith("gemini/"):
        name = name[len("gemini/"):]

    model = ChatGoogleGenerativeAI(
        model=name,
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    logger.info("LangChain Gemini model initialised: %s", name)
    return model


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

@traceable(run_type="llm", name="Generate Plain Response")
def generate_response(
    prompt: str,
    system_instruction: str = "",
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    max_retries: int = 1,
) -> str:
    """
    Generate a plain-text response from Gemini using LangChain wrapper.

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
    model = get_gemini_model(temperature=temperature, max_output_tokens=max_output_tokens)
    
    messages = []
    if system_instruction:
        messages.append(SystemMessage(content=system_instruction))
    messages.append(HumanMessage(content=prompt))

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            start = time.perf_counter()
            response = model.invoke(messages)
            elapsed = time.perf_counter() - start
            logger.info("LangChain Gemini responded in %.2fs (attempt %d)", elapsed, attempt)
            
            if response.content:
                return str(response.content).strip()
            else:
                logger.warning("Empty response from LangChain Gemini on attempt %d", attempt)
                last_error = RuntimeError("Empty response from Gemini")
        except Exception as e:
            logger.warning("LangChain Gemini call failed (attempt %d/%d): %s", attempt, max_retries, e)
            last_error = e
            if attempt < max_retries:
                time.sleep(1.0 * attempt)  # Simple backoff

    raise RuntimeError(f"Gemini generation failed after {max_retries} attempts: {last_error}")


@traceable(run_type="llm", name="Generate Structured Response")
def generate_structured_response(
    prompt: str,
    response_schema: dict[str, Any],
    system_instruction: str = "",
    temperature: float = 0.3,
    max_retries: int = 2,
) -> dict[str, Any]:
    """
    Generate a structured JSON response from Gemini using LangChain wrapper.

    Args:
        prompt: The user prompt.
        response_schema: JSON schema describing expected output structure.
        system_instruction: Optional system instruction.
        temperature: Lower for more deterministic structured output.
        max_retries: Retries on failure.

    Returns:
        Parsed JSON dict.
    """
    model = get_gemini_model(temperature=temperature, max_output_tokens=2048)
    
    # Use Langchain's built-in structured output
    structured_model = model.with_structured_output(schema=response_schema)
    
    messages = []
    if system_instruction:
        messages.append(SystemMessage(content=system_instruction))
    messages.append(HumanMessage(content=prompt))
    
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            start = time.perf_counter()
            response = structured_model.invoke(messages)
            elapsed = time.perf_counter() - start
            logger.info("LangChain Gemini JSON response in %.2fs (attempt %d)", elapsed, attempt)
            
            if response:
                return response
            else:
                last_error = RuntimeError("Empty JSON response")
        except Exception as e:
            logger.warning("LangChain Gemini JSON call failed (attempt %d/%d): %s", attempt, max_retries, e)
            last_error = e
            if attempt < max_retries:
                time.sleep(1.0 * attempt)

    raise RuntimeError(f"Structured generation failed after {max_retries} attempts: {last_error}")

