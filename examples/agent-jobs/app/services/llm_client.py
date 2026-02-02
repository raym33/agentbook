"""LLM client for agent decisions."""
import time
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, requests_per_minute: int = 30):
        self.requests_per_minute = requests_per_minute
        self.requests = []

    def wait_if_needed(self):
        now = time.time()
        self.requests = [t for t in self.requests if now - t < 60]
        if len(self.requests) >= self.requests_per_minute:
            sleep_time = 60 - (now - self.requests[0])
            if sleep_time > 0:
                logger.info(f"Rate limit reached, sleeping {sleep_time:.1f}s")
                time.sleep(sleep_time)
        self.requests.append(time.time())

    def remaining(self) -> int:
        now = time.time()
        self.requests = [t for t in self.requests if now - t < 60]
        return max(0, self.requests_per_minute - len(self.requests))


class LLMClient:
    def __init__(self):
        self.rate_limiter = RateLimiter(settings.llm_rate_limit_per_minute)
        self._backends = [
            ("lm_studio", settings.lm_studio_base_url),
            ("ollama", settings.ollama_base_url),
        ]
        self._active_backend = None

    def _try_lm_studio(self, system: str, prompt: str) -> str | None:
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{settings.lm_studio_base_url}/chat/completions",
                    json={
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1000,
                    },
                )
                if response.status_code == 200:
                    self._active_backend = "lm_studio"
                    return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.debug(f"LM Studio failed: {e}")
        return None

    def _try_ollama(self, system: str, prompt: str) -> str | None:
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{settings.ollama_base_url}/api/generate",
                    json={
                        "model": settings.llm_model,
                        "system": system,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                if response.status_code == 200:
                    self._active_backend = "ollama"
                    return response.json().get("response", "")
        except Exception as e:
            logger.debug(f"Ollama failed: {e}")
        return None

    def chat(self, system: str, prompt: str) -> str:
        """Send a chat request to available LLM backend."""
        self.rate_limiter.wait_if_needed()

        # Try LM Studio first
        result = self._try_lm_studio(system, prompt)
        if result:
            return result

        # Try Ollama
        result = self._try_ollama(system, prompt)
        if result:
            return result

        raise Exception("No LLM backend available")

    def get_backends_status(self) -> dict:
        """Check which backends are available."""
        status = {}

        # Check LM Studio
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{settings.lm_studio_base_url}/models")
                status["lm_studio"] = {"available": r.status_code == 200, "url": settings.lm_studio_base_url}
        except:
            status["lm_studio"] = {"available": False, "url": settings.lm_studio_base_url}

        # Check Ollama
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{settings.ollama_base_url}/api/tags")
                status["ollama"] = {"available": r.status_code == 200, "url": settings.ollama_base_url}
        except:
            status["ollama"] = {"available": False, "url": settings.ollama_base_url}

        return status


llm_client = LLMClient()
