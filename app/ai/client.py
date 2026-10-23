import httpx
import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:3b",
        temperature: float = 0.1,
        timeout: float = 60.0,
        max_retries: int = 1,
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
        options: Dict[str, Any] = {"temperature": self.temperature}
        # Ollama má výchozí kontext jen 2-4k tokenů a delší prompt tichě ořízne (ztrácí instrukce na začátku).
        try:
            options["num_ctx"] = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
            options["num_predict"] = int(os.getenv("OLLAMA_NUM_PREDICT", "2048"))
        except ValueError:
            pass
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": options,
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
