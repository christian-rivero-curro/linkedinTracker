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
            detail = ""
            try:
                err_json = e.response.json()
                detail = f" - {err_json.get('error', {}).get('message', e.response.text)}"
            except Exception:
                detail = f" - {e.response.text[:200]}" if e.response.text else ""
            raise LLMError(f"Error HTTP llamando a OpenRouter ({model}): {e}{detail}") from e


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


def call_llm_structured(
    model: str,
    prompt: str,
    schema_cls,
    max_retries: int = 1,
):
    """
    Llama a OpenRouter y valida estrictamente la respuesta contra un modelo Pydantic.
    Si la respuesta falla la validación de Pydantic o el parseo JSON, reintenta
    retroalimentando el error y el esquema JSON al modelo para corregir la salida.
    """
    from pydantic import ValidationError

    raw_prompt = prompt

    for attempt in range(max_retries + 1):
        try:
            raw = _call_openrouter(model, raw_prompt)
            data = _extract_json(raw)
            if not isinstance(data, dict):
                raise LLMError(f"Se esperaba un objeto JSON (dict) pero se obtuvo {type(data).__name__}")
            return schema_cls.model_validate(data)
        except (json.JSONDecodeError, LLMError, ValidationError) as e:
            if attempt < max_retries:
                schema_hint = ""
                try:
                    schema_hint = f"\nEsquema JSON requerido:\n{json.dumps(schema_cls.model_json_schema(), ensure_ascii=False, indent=2)}\n"
                except Exception:
                    pass
                raw_prompt = (
                    prompt
                    + f"\n\nERROR PREVIO: La salida no cumplio con el esquema esperado ({e}).\n"
                    + schema_hint
                    + "Por favor responde UNICAMENTE con un objeto JSON valido que cumpla este esquema, sin texto adicional ni markdown."
                )
                time.sleep(1.0)
            else:
                raise LLMError(f"Error de validacion Pydantic tras {max_retries + 1} intentos con {model}: {e}") from e

