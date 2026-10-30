# Volitelná vzdálená AI záloha (TODO 11.17)

Výchozí je lokální Ollama. Vzdálený poskytovatel (Groq, OpenAI-kompatibilní API)
se zkusí **jen když lokální model selže** (timeout, nedostupnost, nevalidní výstup).
Kontext zápasu (veřejná, citovaná data s cutoffem) pak odchází mimo stroj.

Zapnutí v `.env` (klíč nikdy nedávejte do gitu ani do logu):

```env
FAE_LLM_PROVIDER=groq
GROQ_API_KEY=...
# volitelné
FAE_REMOTE_LLM_MODEL=llama-3.3-70b-versatile
FAE_REMOTE_LLM_URL=https://api.groq.com/openai/v1
FAE_REMOTE_LLM_TIMEOUT=60
FAE_REMOTE_LLM_RETRIES=2
```

Vypnutí: `FAE_LLM_PROVIDER=ollama` (výchozí) nebo prázdný/chybějící klíč.

Řetěz: Ollama → vzdálený poskytovatel → `insufficient_data`. Validace výstupu
(platná `evidence_ids`, žádný závěr bez podloženého faktoru) i zákaz měnit tip
skóre platí stejně. Výsledek obsahuje `llm_provider` a `llm_model`; chyby
obsahují jen stavový kód, nikdy klíč.

Upozornění: název modelu a limity free tarifu se mění; klient nebyl ověřen proti
živému API (jen testy s `httpx.MockTransport`). Po restartu workeru ověřit
reálným během, že `llm_provider` je `groq` jen při výpadku Ollamy.
