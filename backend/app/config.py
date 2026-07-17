"""Central settings, all driven by environment variables (.env supported).

Swapping SQLite -> PostgreSQL or Ollama -> Gemini is a .env change, not a code change.
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./finaudit.db")

    # "ollama" (local, free) or "gemini" (hosted, for the deployed demo)
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")

    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    ollama_embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    gemini_embed_model: str = os.getenv("GEMINI_EMBED_MODEL", "text-embedding-004")


settings = Settings()
