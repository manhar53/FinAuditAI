"""Provider-agnostic LLM interface.

Everything above this layer calls complete()/embed() and never knows which
provider is behind it. LLM_PROVIDER=ollama for local dev, =gemini for the
deployed demo (Render's free tier can't run Ollama).
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(120.0, connect=5.0)


class LLMUnavailableError(RuntimeError):
    pass


class LLMClient(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str, system: Optional[str] = None) -> str: ...

    @abstractmethod
    def embed(self, text: str) -> Optional[list[float]]: ...

    @abstractmethod
    def available(self) -> bool: ...

    def complete_json(self, prompt: str, system: Optional[str] = None,
                      retries: int = 1) -> Optional[dict]:
        """complete() + tolerant JSON parsing. Small local models wrap JSON in
        prose or emit broken JSON stochastically, so one failed parse gets one
        retry before giving up."""
        for attempt in range(retries + 1):
            try:
                raw = self.complete(prompt, system=system)
            except LLMUnavailableError as e:
                logger.warning("LLM call failed (%s): %s", self.name, e)
                return None
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    pass
            logger.info("Unparseable JSON from %s (attempt %d/%d)", self.name, attempt + 1, retries + 1)
        return None


class OllamaClient(LLMClient):
    name = "ollama"

    def __init__(self):
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.embed_model = settings.ollama_embed_model

    def available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            r = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"Ollama request failed: {e}") from e
        return r.json()["message"]["content"]

    def embed(self, text: str) -> Optional[list[float]]:
        try:
            r = httpx.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            return r.json().get("embedding")
        except httpx.HTTPError as e:
            logger.warning("Ollama embedding failed: %s", e)
            return None


class GeminiClient(LLMClient):
    """Plain REST — avoids the google-generativeai dependency."""

    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self):
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self.embed_model = settings.gemini_embed_model

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            r = httpx.post(
                f"{self.BASE}/models/{self.model}:generateContent",
                params={"key": self.api_key},
                json=body,
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as e:
            # surface Google's error body — a retired model name or bad key is
            # invisible without it
            raise LLMUnavailableError(
                f"Gemini {self.model} returned {e.response.status_code}: {e.response.text[:300]}"
            ) from e
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMUnavailableError(f"Gemini request failed: {e}") from e

    def embed(self, text: str) -> Optional[list[float]]:
        try:
            r = httpx.post(
                f"{self.BASE}/models/{self.embed_model}:embedContent",
                params={"key": self.api_key},
                json={"content": {"parts": [{"text": text}]}},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            return r.json()["embedding"]["values"]
        except (httpx.HTTPError, KeyError) as e:
            logger.warning("Gemini embedding failed: %s", e)
            return None


class NullClient(LLMClient):
    """Used when no provider is reachable. Extraction falls back to regex,
    the query router falls back to keywords — the app degrades, not dies."""

    name = "none"

    def available(self) -> bool:
        return False

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        raise LLMUnavailableError("No LLM provider configured/reachable")

    def embed(self, text: str) -> Optional[list[float]]:
        return None


_client: Optional[LLMClient] = None


def get_llm_client(refresh: bool = False) -> LLMClient:
    """Pick the configured provider; fall back to the other if it's down."""
    global _client
    if _client is not None and not refresh:
        return _client

    order = (
        [OllamaClient(), GeminiClient()]
        if settings.llm_provider == "ollama"
        else [GeminiClient(), OllamaClient()]
    )
    for candidate in order:
        if candidate.available():
            _client = candidate
            logger.info("LLM provider: %s", candidate.name)
            return _client

    logger.warning("No LLM provider reachable — running in rule-based fallback mode")
    _client = NullClient()
    return _client
