"""
Cliente minimo para OpenRouter, usando exclusivamente modelos ":free".
Incluye reintentos con backoff corto ante 429 (rate limit).
"""
import os
import json
import time
import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(Exception):
    pass


def _call_openrouter(model: str, prompt: str, max_retries: int = 2) -> str:
    api_key = os.environ["OPENROUTER_API_KEY"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/linkedinTracker",
        "X-Title": "linkedinTracker",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }

    attempt = 0
    while True:
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(OPENROUTER_URL, headers=headers, json=payload)
            if resp.status_code == 429:
                if attempt >= max_retries:
                    raise LLMError(f"Rate limit persistente en {model}")
                time.sleep(2 ** attempt)
                attempt += 1
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Error HTTP llamando a OpenRouter ({model}): {e}") from e


def _extract_json(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"No se encontro JSON en la respuesta del LLM: {raw_text[:200]}")
    return json.loads(text[start:end + 1])


def call_llm_json(model: str, prompt: str, retry_on_parse_error: bool = True) -> dict:
    """Llama al modelo y valida que la respuesta sea JSON parseable. Reintenta 1 vez si falla el parseo."""
    raw = _call_openrouter(model, prompt)
    try:
        return _extract_json(raw)
    except (json.JSONDecodeError, LLMError):
        if not retry_on_parse_error:
            raise
        reinforced_prompt = prompt + "\n\nIMPORTANTE: responde UNICAMENTE con el JSON valido, sin texto adicional ni backticks."
        raw_retry = _call_openrouter(model, reinforced_prompt)
        return _extract_json(raw_retry)
