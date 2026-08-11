"""
ai/llm_client.py — Multi-Provider LLM Client with automatic waterfall fallback.

Responsibilities:
  - Single entry point for ALL LLM calls in the Prospecting Agent.
  - Detects which providers are configured from the environment.
  - Tries providers in priority order, falling through on rate-limit (429) errors.
  - Applies context-aware truncation: large contexts go to high-capacity providers,
    small-context providers (Groq) auto-truncate the prompt to fit.
  - Returns None (never raises) when all providers are unavailable, so callers
    can skip LLM steps gracefully without crashing.

Provider priority (largest free TPM budget → smallest):
  1. Gemini 1.5 Flash   — 1,000,000 TPM free via Google AI Studio
  2. Cerebras Llama 3.1 — 500,000 tokens/day free
  3. Mistral Nemo/Small — OpenAI-compatible API
  4. Groq llama-3.1-8b  — 6,000 TPM free (existing fallback)

Each provider is OpenAI SDK-compatible (uses openai.AsyncOpenAI with custom base_url).
Groq keeps its native SDK for backward compatibility.

Usage::

    client = LLMClient()
    response = await client.complete(
        system="You are a company researcher...",
        prompt="Summarise this company description: ...",
    )
    if response:
        print(response.content)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_llm_locks = {}
_last_llm_time = 0.0

async def _throttle_llm() -> None:
    """Enforces exactly 1 request per 4.1 seconds (max 14.6 RPM)."""
    global _last_llm_time, _llm_locks
    
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
        
    if loop not in _llm_locks:
        _llm_locks[loop] = asyncio.Lock()
        
    async with _llm_locks[loop]:
        now = time.time()
        elapsed = now - _last_llm_time
        if elapsed < 4.1:
            await asyncio.sleep(4.1 - elapsed)
        _last_llm_time = time.time()


# Context limits per provider (in characters, ~4 chars per token)
_PROVIDER_CONTEXT_LIMITS: dict[str, int] = {
    "gemini":   1_000_000 * 4,   # 1M token context window
    "cerebras": 128_000 * 4,     # 128k token context window
    "mistral":  128_000 * 4,     # 128k token context window
    "groq":     8_000 * 4,       # 8k token effective limit (free TPM ceiling)
}

# OpenAI-compatible base URLs
_PROVIDER_BASE_URLS: dict[str, str] = {
    "gemini":   "https://generativelanguage.googleapis.com/v1beta/openai/",
    "cerebras": "https://api.cerebras.ai/v1",
    "mistral":  "https://api.mistral.ai/v1",
    # Groq uses its own SDK, not openai client
}

# Retryable HTTP status codes
_RETRYABLE_STATUSES = {500, 502, 503, 529}

# Rate-limit status code — triggers immediate fallback to next provider
_RATELIMIT_STATUS = 429


@dataclass
class LLMResponse:
    """Structured response from an LLM completion call."""
    content: str
    model_used: str
    provider_used: str
    tokens_used: int = 0
    fallback_used: bool = False


class LLMClient:
    """
    Multi-provider async LLM client with waterfall fallback.

    Automatically detects configured providers from environment.
    Falls through the chain on rate-limit errors.
    """

    def __init__(self) -> None:
        from apps.api.modules.prospecting.engine.config import get_settings
        self._settings = get_settings()
        self._provider_chain: list[str] = self._build_provider_chain()

        if not self._provider_chain:
            logger.warning(
                "LLMClient: No LLM providers configured. "
                "Set GEMINI_API_KEY, CEREBRAS_API_KEY, MISTRAL_API_KEY, or GROQ_API_KEY in .env."
            )
        else:
            logger.info(
                "LLMClient: Active provider chain = %s",
                " -> ".join(self._provider_chain)
            )

    def _build_provider_chain(self) -> list[str]:
        """Build ordered list of available providers based on configured keys."""
        chain = []
        if self._settings.gemini_api_key:
            chain.append("gemini")
        if self._settings.mistral_api_key:
            chain.append("mistral")
        if self._settings.groq_api_key:
            chain.append("groq")
        return chain

    @property
    def available_providers(self) -> list[str]:
        return list(self._provider_chain)

    @property
    def is_enabled(self) -> bool:
        return bool(self._provider_chain)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        system: str = "You are a helpful assistant.",
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse | None:
        """
        Make a completion call, waterfalling through providers on rate-limit.

        Returns LLMResponse or None if all providers fail or none are configured.
        """
        if not self._provider_chain:
            return None

        max_tok = max_tokens or 4096
        is_first = True

        await _throttle_llm()

        for provider in self._provider_chain:
            truncated_prompt = self._truncate_for_provider(prompt, provider)
            result = await self._call_provider(
                provider=provider,
                system=system,
                prompt=truncated_prompt,
                max_tokens=max_tok,
                temperature=temperature,
                fallback_used=not is_first,
            )

            if result is not None:
                return result

            is_first = False

        logger.error("LLMClient: All configured providers failed. LLM step skipped.")
        return None

    # -------------------------------------------------------------------------
    # Per-provider dispatch
    # -------------------------------------------------------------------------

    def _truncate_for_provider(self, prompt: str, provider: str) -> str:
        """Truncate prompt to fit provider's context window."""
        limit = _PROVIDER_CONTEXT_LIMITS.get(provider, 32_000)
        if len(prompt) > limit:
            truncated = prompt[:limit]
            logger.debug(
                "LLMClient: Prompt truncated from %d to %d chars for provider '%s'",
                len(prompt), limit, provider
            )
            return truncated + "\n...[content truncated to fit model context]..."
        return prompt

    async def _call_provider(
        self,
        provider: str,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        fallback_used: bool,
    ) -> LLMResponse | None:
        """Dispatch to the appropriate provider handler."""
        if provider == "groq":
            return await self._call_groq_native(
                system=system,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                fallback_used=fallback_used,
            )
            
        if provider == "gemini":
            return await self._call_gemini_native(
                system=system,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                fallback_used=fallback_used,
            )

        if provider == "mistral":
            return await self._call_openai_compatible(
                provider=provider,
                system=system,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                fallback_used=fallback_used,
            )
        return None

    async def _call_openai_compatible(
        self,
        provider: str,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        fallback_used: bool,
        max_retries: int = 2,
    ) -> LLMResponse | None:
        """Call any OpenAI-compatible endpoint (Mistral, etc)."""
        key, model = self._get_key_and_model(provider)
        base_url = _PROVIDER_BASE_URLS[provider]

        try:
            from openai import AsyncOpenAI, RateLimitError, APIStatusError  # noqa: PLC0415
        except ImportError:
            logger.error("LLMClient: 'openai' package not installed. Run: pip install openai")
            return None

        client = AsyncOpenAI(api_key=key, base_url=base_url, timeout=45.0)

        for attempt in range(1, max_retries + 1):
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                content = response.choices[0].message.content or ""
                tokens = response.usage.total_tokens if response.usage else 0
                logger.debug(
                    "LLMClient: %s completion OK — model=%s tokens=%d fallback=%s",
                    provider, model, tokens, fallback_used,
                )
                return LLMResponse(
                    content=content,
                    model_used=model,
                    provider_used=provider,
                    tokens_used=tokens,
                    fallback_used=fallback_used,
                )

            except RateLimitError:
                logger.warning(
                    "LLMClient: Rate limit hit on '%s' — falling back to next provider.",
                    provider
                )
                return None  # Immediate fallback, no retry on rate limit

            except APIStatusError as exc:
                # If provider returns 404 (model not found) or 402 (payment required), fallback cleanly
                if exc.status_code in (404, 402):
                    logger.warning("LLMClient: %s status %d (payment/model error) — falling back to next provider.", provider, exc.status_code)
                    return None
                    
                if exc.status_code in _RETRYABLE_STATUSES and attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "LLMClient: %s transient error (attempt %d/%d) status=%d — retrying in %ds",
                        provider, attempt, max_retries, exc.status_code, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("LLMClient: %s non-retryable error: %s", provider, exc)
                    return None

            except Exception as exc:
                logger.error("LLMClient: unexpected failure using '%s': %s", provider, exc)
                continue
        
        logger.warning("LLMClient: All %d LLM providers failed. Request dropped.", len(self._provider_chain))
        return None

    async def _call_gemini_native(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        fallback_used: bool,
        max_retries: int = 2,
    ) -> LLMResponse | None:
        """Call Gemini using the official google-generativeai SDK."""
        key, model_name = self._get_key_and_model("gemini")
        
        try:
            from google import genai
            from google.genai.errors import APIError
        except ImportError:
            logger.error("LLMClient: 'google-genai' package not installed. Run: pip install google-genai")
            return None

        client = genai.Client(
            api_key=key,
            http_options={'timeout': 45000}  # 45 seconds in ms for some versions, or it uses httpx timeout config
        )
        
        config = genai.types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        for attempt in range(1, max_retries + 1):
            try:
                # Use the new .aio (async) client
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                
                content = response.text
                
                tokens = 0
                if response.usage_metadata:
                    tokens = response.usage_metadata.total_token_count
                
                logger.debug(
                    "LLMClient: gemini completion OK — model=%s tokens=%d fallback=%s",
                    model_name, tokens, fallback_used,
                )
                return LLMResponse(
                    content=content,
                    model_used=model_name,
                    provider_used="gemini",
                    tokens_used=tokens,
                    fallback_used=fallback_used,
                )

            except APIError as exc:
                if exc.code == 429:
                    logger.warning("LLMClient: Rate limit hit on 'gemini' — falling back to next provider.")
                    return None
                    
                if exc.code in (404, 400, 402, 403):
                    logger.warning("LLMClient: gemini non-retryable API error (status %s): %s — falling back.", exc.code, exc.message)
                    return None
                
                logger.error("LLMClient: gemini retryable APIError: %s", exc)
                if attempt == max_retries:
                    return None
                await asyncio.sleep(1.5 ** attempt)
            except Exception as exc:
                logger.error("LLMClient: gemini non-retryable error: %s", exc)
                return None

        return None

    async def _call_groq_native(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        fallback_used: bool,
        max_retries: int = 3,
    ) -> LLMResponse | None:
        """Call Groq using its native SDK (preserves existing behaviour)."""
        try:
            from groq import Groq  # noqa: PLC0415
        except ImportError:
            logger.error("LLMClient: 'groq' package not installed. Run: pip install groq")
            return None

        _, model = self._get_key_and_model("groq")
        client = Groq(api_key=self._settings.groq_api_key, timeout=45.0)

        for attempt in range(1, max_retries + 1):
            try:
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
                tokens = response.usage.total_tokens if hasattr(response, "usage") else 0
                logger.debug(
                    "LLMClient: groq completion OK — model=%s tokens=%d fallback=%s",
                    model, tokens, fallback_used,
                )
                return LLMResponse(
                    content=content,
                    model_used=model,
                    provider_used="groq",
                    tokens_used=tokens,
                    fallback_used=fallback_used,
                )

            except Exception as exc:
                exc_name = type(exc).__name__
                status_code = getattr(exc, "status_code", None)

                # Rate limit — immediate fallback
                if status_code == _RATELIMIT_STATUS:
                    logger.warning("LLMClient: Groq rate limit hit — no more providers in chain.")
                    return None

                # Non-retryable
                if status_code in (400, 401, 403):
                    logger.error("LLMClient: Groq non-retryable error (%s): %s", status_code, exc)
                    return None

                # Retryable
                wait = 2 ** attempt
                logger.warning(
                    "LLMClient: Groq transient error [%d/%d] %s(%s) — retrying in %ds",
                    attempt, max_retries, exc_name, exc, wait,
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait)

        return None

    def _get_key_and_model(self, provider: str) -> tuple[str, str]:
        """Retrieve the API key and model name for a given provider from settings."""
        if provider == "gemini":
            return self._settings.gemini_api_key or "", self._settings.gemini_model
        if provider == "mistral":
            return self._settings.mistral_api_key or "", self._settings.mistral_model
        if provider == "groq":
            return self._settings.groq_api_key or "", self._settings.groq_primary_model
        return "", ""
