import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    backend: str
    tokens_used: int
    latency_ms: float


class LLMBackend(ABC):
    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str, **kwargs) -> LLMResponse:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


class LMStudioBackend(LLMBackend):
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "lmstudio"

    def chat(self, system_prompt: str, user_prompt: str, **kwargs) -> LLMResponse:
        start = time.time()
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 256),
        }
        response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        latency = (time.time() - start) * 1000

        return LLMResponse(
            content=data["choices"][0]["message"]["content"].strip(),
            model=self.model,
            backend=self.name,
            tokens_used=data.get("usage", {}).get("total_tokens", 0),
            latency_ms=latency,
        )

    def is_available(self) -> bool:
        try:
            requests.get(f"{self.base_url}/v1/models", timeout=2)
            return True
        except Exception:
            return False


class OllamaBackend(LLMBackend):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama2"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    @property
    def name(self) -> str:
        return "ollama"

    def chat(self, system_prompt: str, user_prompt: str, **kwargs) -> LLMResponse:
        start = time.time()
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        latency = (time.time() - start) * 1000

        return LLMResponse(
            content=data["message"]["content"],
            model=self.model,
            backend=self.name,
            tokens_used=data.get("eval_count", 0),
            latency_ms=latency,
        )

    def is_available(self) -> bool:
        try:
            requests.get(f"{self.base_url}/api/tags", timeout=2)
            return True
        except Exception:
            return False


class OpenAIBackend(LLMBackend):
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    @property
    def name(self) -> str:
        return "openai"

    def chat(self, system_prompt: str, user_prompt: str, **kwargs) -> LLMResponse:
        start = time.time()
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 256),
        }
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        latency = (time.time() - start) * 1000

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=self.model,
            backend=self.name,
            tokens_used=data.get("usage", {}).get("total_tokens", 0),
            latency_ms=latency,
        )

    def is_available(self) -> bool:
        return bool(self.api_key)


class AnthropicBackend(LLMBackend):
    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307"):
        self.api_key = api_key
        self.model = model

    @property
    def name(self) -> str:
        return "anthropic"

    def chat(self, system_prompt: str, user_prompt: str, **kwargs) -> LLMResponse:
        start = time.time()
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": self.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": kwargs.get("max_tokens", 256),
        }
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        latency = (time.time() - start) * 1000

        content = data["content"][0]["text"] if data.get("content") else ""
        tokens = data.get("usage", {})
        total_tokens = tokens.get("input_tokens", 0) + tokens.get("output_tokens", 0)

        return LLMResponse(
            content=content,
            model=self.model,
            backend=self.name,
            tokens_used=total_tokens,
            latency_ms=latency,
        )

    def is_available(self) -> bool:
        return bool(self.api_key)


class RateLimiter:
    def __init__(self, requests_per_minute: int = 30):
        self.requests_per_minute = requests_per_minute
        self.timestamps: list[float] = []

    def acquire(self) -> bool:
        now = time.time()
        self.timestamps = [t for t in self.timestamps if now - t < 60]
        if len(self.timestamps) >= self.requests_per_minute:
            return False
        self.timestamps.append(now)
        return True

    def wait_time(self) -> float:
        if not self.timestamps:
            return 0
        oldest = min(self.timestamps)
        return max(0, 60 - (time.time() - oldest))

    def remaining(self) -> int:
        now = time.time()
        self.timestamps = [t for t in self.timestamps if now - t < 60]
        return self.requests_per_minute - len(self.timestamps)


class MultiBackendLLMClient:
    def __init__(self):
        self.backends: list[LLMBackend] = []
        self.rate_limiter = RateLimiter(settings.llm_rate_limit_per_minute)
        self._setup_backends()

    def _setup_backends(self):
        # Primary: LM Studio
        self.backends.append(
            LMStudioBackend(
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                timeout=settings.llm_timeout_seconds,
            )
        )

        # Fallback: Ollama
        if settings.ollama_base_url:
            self.backends.append(
                OllamaBackend(
                    base_url=settings.ollama_base_url,
                    model=settings.ollama_model,
                )
            )

        # Fallback: OpenAI
        if settings.openai_api_key:
            self.backends.append(
                OpenAIBackend(
                    base_url=settings.openai_base_url,
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                )
            )

        # Fallback: Anthropic
        if settings.anthropic_api_key:
            self.backends.append(
                AnthropicBackend(
                    api_key=settings.anthropic_api_key,
                    model=settings.anthropic_model,
                )
            )

    def get_backends_status(self) -> list[dict]:
        return [
            {
                "name": backend.name,
                "available": backend.is_available(),
            }
            for backend in self.backends
        ]

    def chat(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        if not self.rate_limiter.acquire():
            wait = self.rate_limiter.wait_time()
            logger.warning(f"Rate limit reached, waiting {wait:.1f}s")
            time.sleep(wait)
            self.rate_limiter.acquire()

        for backend in self.backends:
            if backend.is_available():
                try:
                    response = backend.chat(system_prompt, user_prompt, **kwargs)
                    logger.debug(f"LLM response from {backend.name} in {response.latency_ms:.0f}ms")
                    return response.content
                except Exception as e:
                    logger.warning(f"Backend {backend.name} failed: {e}")
                    continue

        raise RuntimeError("No LLM backend available")

    def chat_with_metadata(self, system_prompt: str, user_prompt: str, **kwargs) -> LLMResponse:
        if not self.rate_limiter.acquire():
            wait = self.rate_limiter.wait_time()
            time.sleep(wait)
            self.rate_limiter.acquire()

        for backend in self.backends:
            if backend.is_available():
                try:
                    return backend.chat(system_prompt, user_prompt, **kwargs)
                except Exception as e:
                    logger.warning(f"Backend {backend.name} failed: {e}")
                    continue

        raise RuntimeError("No LLM backend available")


llm_client = MultiBackendLLMClient()
