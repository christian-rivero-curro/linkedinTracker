"""
Cliente para JSearch API (RapidAPI), free tier 200 req/mes.
Devuelve ofertas con enlace directo (LinkedIn cuando la fuente original lo es).

JSEARCH_SOURCE_FILTER restringe la busqueda a un publisher concreto (por
defecto 'linkedin'). JSearch no expone un parametro de API estricto para esto;
la forma documentada de acotar por fuente es anadir "via <publisher>" al texto
de la query (ver docs de OpenWeb Ninja). No es una garantia al 100% - por eso
run_discovery.py aplica ademas un filtro de seguridad en base al job_publisher
ya clasificado (normalize_job) antes de guardar cualquier oferta.
"""
import os
import httpx

JSEARCH_BASE_URL = "https://jsearch.p.rapidapi.com/search"


def _source_filter_suffix() -> str:
    source = os.environ.get("JSEARCH_SOURCE_FILTER", "linkedin").strip().lower()
    return f" via {source}" if source else ""


def search_jobs(query: str, location: str | None, remote_only: bool, page: int = 1, date_posted: str = "week") -> list[dict]:
    api_key = os.environ["RAPIDAPI_KEY"]
    host = os.environ.get("RAPIDAPI_JSEARCH_HOST", "jsearch.p.rapidapi.com")
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": host}

    full_query = f"{query} in {location}" if location else query
    full_query = f"{full_query}{_source_filter_suffix()}"

    params = {
        "query": full_query,
        "page": str(page),
        "num_pages": "1",
        "date_posted": date_posted,
        "employment_types": "FULLTIME",
    }
    if remote_only:
        params["remote_jobs_only"] = "true"

    with httpx.Client(timeout=30) as client:
        resp = client.get(JSEARCH_BASE_URL, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps(data, indent=2)[:2000])

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


def _clean_text(value):
    """
    Normaliza cualquier valor a un str seguro para DB/embeddings, o None si el
    valor original era None (preserva nullability de campos opcionales).

    Fuerza a str si la API devuelve un tipo inesperado (list, dict, numero) en
    vez de propagar ese tipo aguas abajo, y elimina caracteres Unicode invalidos
    (surrogates sueltos, mojibake) que a veces llegan en texto agregado desde
    sitios externos (Jobrapido, Bing Jobs, Jooble...). Sin esto, tanto el
    tokenizer de embeddings como la escritura UTF-8 en Postgres fallan con
    errores dificiles de rastrear.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value.encode("utf-8", errors="ignore").decode("utf-8")


def _clean_int(value):
    """Coacciona a int de forma segura (salarios); None si no es convertible."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_bool(value) -> bool:
    """Coacciona a bool de forma segura: la API a veces devuelve 'true'/'false' como
    string en vez de bool nativo, y bool('false') seria True si no se maneja aqui."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


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
