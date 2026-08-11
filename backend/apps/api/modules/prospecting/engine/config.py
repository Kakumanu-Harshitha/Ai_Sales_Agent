"""
engine/config.py - Engine settings adapter.

Bridges the standalone engine's get_settings() interface to the main
SETV app's Settings object so all engine code works without modification.
"""

from __future__ import annotations


class EngineSettings:
    """Adapter that maps main app env vars to the engine's expected interface."""

    def __init__(self) -> None:
        from apps.api.core.config import settings as _s
        self._s = _s

    @property
    def groq_api_key(self) -> str | None:
        return self._s.GROQ_API_KEY

    @property
    def groq_primary_model(self) -> str:
        return self._s.GROQ_MODEL

    @property
    def groq_fallback_model(self) -> str | None:
        return getattr(self._s, "GROQ_FALLBACK_MODEL", None) or self._s.GROQ_MODEL

    @property
    def groq_max_tokens(self) -> int:
        return 4096

    @property
    def groq_temperature(self) -> float:
        return 0.2

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def gemini_api_key(self) -> str | None:
        return getattr(self._s, "GEMINI_API_KEY", None)

    @property
    def gemini_model(self) -> str:
        return getattr(self._s, "GEMINI_MODEL", "gemini-1.5-flash")

    @property
    def cerebras_api_key(self) -> str | None:
        return getattr(self._s, "CEREBRAS_API_KEY", None)

    @property
    def cerebras_model(self) -> str:
        return getattr(self._s, "CEREBRAS_MODEL", "llama3.1-8b")

    @property
    def mistral_api_key(self) -> str | None:
        return getattr(self._s, "MISTRAL_API_KEY", None)

    @property
    def mistral_model(self) -> str:
        return getattr(self._s, "MISTRAL_MODEL", "mistral-small-latest")

    @property
    def llm_enabled(self) -> bool:
        """True if at least one LLM provider is configured."""
        return bool(
            self.gemini_api_key or self.cerebras_api_key
            or self.mistral_api_key or self.groq_api_key
        )

    @property
    def tavily_api_key(self) -> str | None:
        return self._s.TAVILY_API_KEY

    @property
    def tavily_enabled(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def tavily_base_url(self) -> str:
        return "https://api.tavily.com"

    @property
    def serper_api_key(self) -> str | None:
        return self._s.SERPER_API_KEY

    @property
    def apollo_api_key(self) -> str | None:
        return getattr(self._s, "APOLLO_API_KEY", None)

    @property
    def apollo_enabled(self) -> bool:
        return bool(self.apollo_api_key)

    @property
    def apollo_base_url(self) -> str:
        return "https://api.apollo.io/api/v1"

    @property
    def apollo_discovery_enabled(self) -> bool:
        return getattr(self._s, "APOLLO_DISCOVERY_ENABLED", False)

    @property
    def apollo_enrichment_enabled(self) -> bool:
        return getattr(self._s, "APOLLO_ENRICHMENT_ENABLED", True)

    @property
    def hunter_api_key(self) -> str | None:
        return self._s.HUNTER_API_KEY

    @property
    def hunter_enabled(self) -> bool:
        return bool(self.hunter_api_key)

    @property
    def hunter_base_url(self) -> str:
        return "https://api.hunter.io/v2"

    @property
    def pdl_api_key(self) -> str | None:
        return getattr(self._s, "PDL_API_KEY", None)

    @property
    def pdl_enabled(self) -> bool:
        return bool(self.pdl_api_key)

    @property
    def pdl_base_url(self) -> str:
        return "https://api.peopledatalabs.com/v5"

    @property
    def abstract_api_key(self) -> str | None:
        return getattr(self._s, "ABSTRACT_API_KEY", None)

    @property
    def abstract_enabled(self) -> bool:
        return bool(self.abstract_api_key)

    @property
    def abstract_base_url(self) -> str:
        return "https://companyenrichment.abstractapi.com/v1"

    @property
    def skrapp_api_key(self) -> str | None:
        return getattr(self._s, "SKRAPP_API_KEY", None)

    @property
    def prospeo_api_key(self) -> str | None:
        return getattr(self._s, "PROSPEO_API_KEY", None)

    @property
    def tinyfish_api_key(self) -> str | None:
        return getattr(self._s, "TINYFISH_API_KEY", None)

    @property
    def tinyfish_enabled(self) -> bool:
        return bool(self.tinyfish_api_key)

    @property
    def npi_registry_url(self) -> str:
        return "https://npiregistry.cms.hhs.gov/api"

    @property
    def max_companies_per_search(self) -> int:
        return getattr(self._s, "MAX_COMPANIES_PER_SEARCH", 50)

    @property
    def qualification_threshold(self) -> int:
        return getattr(self._s, "QUALIFICATION_THRESHOLD", 40)

    @property
    def provider_timeout_seconds(self) -> int:
        return getattr(self._s, "PROVIDER_TIMEOUT_SECONDS", 15)

    @property
    def max_concurrent_research(self) -> int:
        return getattr(self._s, "MAX_CONCURRENT_RESEARCH", 5)

    @property
    def cache_ttl_seconds(self) -> int:
        return getattr(self._s, "CACHE_TTL_SECONDS", 3600)

    @property
    def provider_max_retries(self) -> int:
        return getattr(self._s, "PROVIDER_MAX_RETRIES", 3)

    @property
    def provider_retry_backoff_base(self) -> float:
        return getattr(self._s, "PROVIDER_RETRY_BACKOFF_BASE", 2.0)


_settings = EngineSettings()


def get_settings() -> EngineSettings:
    return _settings
