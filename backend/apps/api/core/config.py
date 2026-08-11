from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file=".env", env_file_encoding="utf-8")
    
    ENVIRONMENT: str = "dev"
    DATABASE_URL: str

    # AI Keys
    OPENAI_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    GROQ_API_KEYS: str | None = None
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    GROQ_FALLBACK_MODEL: str | None = None
    GROQ_FALLBACK_MODELS: str | None = None

    # Multi-Provider LLM fallback chain
    GEMINI_API_KEY: str | None = None      # Free at aistudio.google.com
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    
    MISTRAL_API_KEY: str | None = None     # Free tier at console.mistral.ai
    MISTRAL_MODEL: str = "mistral-small-latest"

    HUNTER_API_KEY: str | None = None
    TAVILY_API_KEY: str | None = None
    SERPER_API_KEY: str | None = None

    # Apollo (people enrichment, not company discovery)
    APOLLO_API_KEY: str | None = None
    APOLLO_DISCOVERY_ENABLED: bool = False
    APOLLO_ENRICHMENT_ENABLED: bool = True

    # People Data Labs (contact enrichment — 1,000 free/month)
    PDL_API_KEY: str | None = None

    # Abstract API (company enrichment — 1,000 free/month)
    ABSTRACT_API_KEY: str | None = None

    # Additional email enrichment providers
    PROSPEO_API_KEY: str | None = None
    SKRAPP_API_KEY: str | None = None       # Removed — kept for backward compat
    GETPROSPECT_API_KEY: str | None = None  # Removed — kept for backward compat

    # TinyFish (AI web agent search — free tier)
    TINYFISH_API_KEY: str | None = None

    # Prospecting Behaviour
    MAX_COMPANIES_PER_SEARCH: int = 50
    QUALIFICATION_THRESHOLD: int = 40
    PROVIDER_TIMEOUT_SECONDS: int = 15
    MAX_CONCURRENT_RESEARCH: int = 2

    # Auth
    JWT_SECRET: str | None = None

    # Google OAuth (Calendar + Gmail)
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str | None = None
    GMAIL_REFRESH_TOKEN: str | None = None
    GOOGLE_CREDENTIALS_PATH: str = "credentials.json"

    # SMTP Fallback
    SMTP_HOST: str | None = None
    SMTP_PORT: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None

    # Scheduler
    APSCHEDULER_TIMEZONE: str = "UTC"

settings = Settings()
