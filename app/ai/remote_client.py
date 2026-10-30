"""Volitelný vzdálený LLM poskytovatel (TODO 11.17) – pouze jako záloha za lokální Ollamou.

Používá OpenAI-kompatibilní endpoint `/chat/completions` (výchozí Groq). Na rozdíl od
Ollamy odchází kontext zápasu (veřejná, citovaná data) mimo stroj, proto se klient
vytváří jen při výslovném zapnutí `FAE_LLM_PROVIDER=groq` a nastaveném `GROQ_API_KEY`.
API klíč se nikdy neloguje ani neukládá do výsledků/chyb.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
_RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class RemoteLLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.1,
        timeout: float = 60.0,
        max_retries: int = 2,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        if not str(api_key or "").strip():
            raise ValueError("Chybí API klíč vzdáleného LLM.")
        self._api_key = str(api_key).strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.transport = transport  # pouze pro testy
        self.json_schema: Optional[Dict[str, Any]] = None  # kompatibilita s OllamaClient

    def _sanitize(self, text: str) -> str:
        return str(text).replace(self._api_key, "[REDACTED_KEY]")[:300]

    def generate(self, prompt: str, system_prompt: Optional[str] = None, require_json: bool = True) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        body: Dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if require_json:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        last_error = "neznámá chyba"
        for attempt in range(1, self.max_retries + 1):
            retry = True
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                    resp = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
                if resp.status_code >= 400:
                    # Tělo odpovědi ani URL se nevypisují – jen stavový kód.
                    last_error = f"HTTP {resp.status_code}"
                    retry = resp.status_code in _RETRY_STATUS
                else:
                    data = resp.json()
                    content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content")
                    if isinstance(content, str) and content.strip():
                        return content
                    last_error = "odpověď neobsahuje text"
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {self._sanitize(exc)}"
            logger.warning("Vzdálený LLM, pokus %d/%d selhal: %s", attempt, self.max_retries, last_error)
            if not retry:
                break
            if attempt < self.max_retries:
                time.sleep(min(2 ** (attempt - 1), 4))
        raise RuntimeError(f"Vzdálený LLM selhal: {last_error}")
