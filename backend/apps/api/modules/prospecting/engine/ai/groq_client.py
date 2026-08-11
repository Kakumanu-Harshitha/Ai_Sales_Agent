"""
ai/groq_client.py â€” Groq LLM client wrapper.

Responsibilities:
  - Single point of entry for all LLM calls in the Prospecting Agent.
  - Primary model: llama-3.3-70b-versatile
  - Fallback model: llama3-70b-8192
  - Automatic retry on 503 / 529 with exponential backoff.
  - Automatic model downgrade on primary model failure.
  - Returns None (never raises) when Groq is not configured or all retries fail,
    so callers can gracefully skip LLM steps without crashing.

This module is the ONLY place in the codebase that imports `groq`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from apps.api.modules.prospecting.engine.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Structured response from a Groq completion call."""
    content: str
    model_used: str
    tokens_used: int = 0
    fallback_used: bool = False


class GroqClient:
    """
    Async-compatible Groq LLM client with primary/fallback model support.

    Usage::

        client = GroqClient()
        response = await client.complete(
            system="You are a company researcher...",
            prompt="Summarise this company description: ...",
        )
        if response:
            print(response.content)
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: Any = None  # Lazy-init on first call

        if not self._settings.groq_enabled:
            logger.warning(
                "Groq API key not configured. "
                "LLM-based company research and qualification reasoning are disabled."
            )

    def _get_client(self) -> Any:
        """Lazy-initialise the Groq client (avoids import errors when key is absent)."""
        if self._client is None:
            try:
                from groq import Groq  # noqa: PLC0415
                self._client = Groq(api_key=self._settings.groq_api_key)
            except ImportError:
                logger.error("groq package is not installed. Run: pip install groq")
                return None
        return self._client

    async def complete(
        self,
        prompt: str,
        system: str = "You are a helpful assistant.",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse | None:
        """
        Make a completion call to Groq.

        Returns None if:
          - Groq API key is not configured
          - All retry attempts on both models fail
        """
        if not self._settings.groq_enabled:
            return None

        client = self._get_client()
        if client is None:
            return None

        max_tok = max_tokens or self._settings.groq_max_tokens
        temp = temperature if temperature is not None else self._settings.groq_temperature

        # Try primary model first, then fall back
        for attempt_model, is_fallback in [
            (self._settings.groq_primary_model, False),
            (self._settings.groq_fallback_model, True),
        ]:
            result = await self._call_with_retry(
                client=client,
                model=attempt_model,
                system=system,
                prompt=prompt,
                max_tokens=max_tok,
                temperature=temp,
                is_fallback=is_fallback,
            )
            if result is not None:
                return result
            logger.warning(
                "Model %s failed â€” %s",
                attempt_model,
                "trying fallback" if not is_fallback else "no more fallbacks",
            )

        logger.error("All Groq models failed. LLM step skipped.")
        return None

    async def _call_with_retry(
        self,
        client: Any,
        model: str,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        is_fallback: bool,
        max_retries: int = 3,
    ) -> LLMResponse | None:
        """Attempt a single model call with exponential backoff on transient errors."""
        for attempt in range(1, max_retries + 1):
            try:
                # Groq SDK is sync â€” run in executor to avoid blocking the event loop
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                )
                content = response.choices[0].message.content or ""
                tokens = (
                    response.usage.total_tokens if hasattr(response, "usage") else 0
                )
                logger.debug(
                    "Groq completion: model=%s tokens=%d fallback=%s",
                    model, tokens, is_fallback,
                )
                return LLMResponse(
                    content=content,
                    model_used=model,
                    tokens_used=tokens,
                    fallback_used=is_fallback,
                )

            except Exception as exc:  # noqa: BLE001
                exc_name = type(exc).__name__
                status_code = getattr(exc, "status_code", None)

                # Non-retryable errors
                if status_code in (400, 401, 403):
                    logger.error(
                        "Groq non-retryable error (%s) on model %s: %s",
                        status_code, model, exc,
                    )
                    return None

                # Retryable (503, 529, 429, network errors)
                wait = 2 ** attempt
                logger.warning(
                    "Groq transient error [attempt %d/%d] model=%s error=%s(%s) â€” "
                    "retrying in %ds",
                    attempt, max_retries, model, exc_name, exc, wait,
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait)

        return None

