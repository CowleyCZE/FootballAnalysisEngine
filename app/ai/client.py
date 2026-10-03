import httpx
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:7b",
        temperature: float = 0.1,
        timeout: float = 180.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        require_json: bool = True,
    ) -> str:
        url = f"{self.base_url}/api/generate"
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt
        if require_json:
            payload["format"] = "json"

        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    return data.get("response", "")
            except Exception as e:
                logger.warning(f"Ollama call attempt {attempt}/{self.max_retries} failed: {e}")
                last_exception = e

        raise RuntimeError(f"Ollama API request failed after {self.max_retries} retries: {last_exception}")
