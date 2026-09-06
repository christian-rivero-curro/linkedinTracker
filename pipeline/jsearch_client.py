"""
Cliente para JSearch API (RapidAPI), free tier 200 req/mes.
Devuelve ofertas con enlace directo (LinkedIn cuando la fuente original lo es).

Notas sobre /search-v2 (segun documentacion oficial de OpenWeb Ninja):
- La lista real de ofertas esta en data['data']['jobs'] (con 'cursor' para paginacion),
  no directamente en data['data'] como en la v1.
- Para queries fuera de EE.UU. hay que combinar 'country' Y 'language'.
- El filtro de solo remoto se llama 'work_from_home' (no 'remote_jobs_only').
- date_posted='week' puede devolver 0 resultados para roles de nicho en ciudades
  concretas (validado manualmente); por defecto se usa 'month' via JSEARCH_DATE_POSTED.
- No existe parametro de ordenacion (sort_by): el orden de resultados es la
  relevancia interna de Google for Jobs, no cronologico. Por eso el filtrado
  real por fecha se hace del lado del cliente en pipeline/run_discovery.py
  usando job_posted_at_datetime_utc, sin confiar en el orden de la respuesta.
- num_pages controla cuantas paginas agrega la API en una sola llamada
  (server-side). Empezar en 1 y subir solo tras verificar en el dashboard de
  RapidAPI si num_pages>1 consume mas de 1 credito por llamada.
"""
import os
import json
import httpx

JSEARCH_BASE_URL = "https://jsearch.p.rapidapi.com/search-v2"


def search_jobs(
    query: str,
    location: str | None,
    remote_only: bool,
    date_posted: str | None = None,
    num_pages: int | None = None,
) -> list[dict]:
    api_key = os.environ["RAPIDAPI_KEY"]
    host = os.environ.get("RAPIDAPI_JSEARCH_HOST", "jsearch.p.rapidapi.com")
    country = os.environ.get("JSEARCH_COUNTRY", "es")
    language = os.environ.get("JSEARCH_LANGUAGE", "en")
    if date_posted is None:
        date_posted = os.environ.get("JSEARCH_DATE_POSTED", "month")
    if num_pages is None:
        num_pages = int(os.environ.get("JSEARCH_NUM_PAGES", "1"))

    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": host}
    params = {
        "query": f"{query} in {location}" if location else query,
        "page": "1",
        "num_pages": str(max(1, num_pages)),
        "country": country,
        "language": language,
        "date_posted": date_posted,
        "employment_types": "FULLTIME",
    }
    if remote_only:
        params["work_from_home"] = "true"

    with httpx.Client(timeout=30) as client:
        resp = client.get(JSEARCH_BASE_URL, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()

    data_field = data.get("data", [])
    if isinstance(data_field, dict):
        raw_items = data_field.get("jobs", [])
    else:
        raw_items = data_field

    jobs: list[dict] = []
    for item in raw_items:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                print(f"[jsearch_client] Entrada no es JSON valido, se ignora: {item[:200]}")
                continue
        if isinstance(item, dict):
            jobs.append(item)
        else:
            print(f"[jsearch_client] Entrada con tipo inesperado ({type(item)}), se ignora.")
    return jobs


def normalize_job(raw: dict) -> dict:
    publisher = (raw.get("job_publisher") or "").lower()
    source = "linkedin" if "linkedin" in publisher else ("indeed" if "indeed" in publisher else "other")
    return {
        "external_id": raw.get("job_id"),
        "title": raw.get("job_title") or "Sin titulo",
        "company": raw.get("employer_name"),
        "location": raw.get("job_city") or raw.get("job_country"),
        "remote_type": "remote" if raw.get("job_is_remote") else "onsite",
        "description": raw.get("job_description") or "",
        "apply_link": raw.get("job_apply_link") or raw.get("job_google_link") or "",
        "source": source,
        "salary_min": raw.get("job_min_salary"),
        "salary_max": raw.get("job_max_salary"),
        "posted_at": raw.get("job_posted_at_datetime_utc"),
    }
