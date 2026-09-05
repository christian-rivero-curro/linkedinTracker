"""
Cliente para JSearch API (RapidAPI), free tier 200 req/mes.
Devuelve ofertas con enlace directo (LinkedIn cuando la fuente original lo es).
"""
import os
import httpx

JSEARCH_BASE_URL = "https://jsearch.p.rapidapi.com/search"


def search_jobs(query: str, location: str | None, remote_only: bool, date_posted: str = "week") -> list[dict]:
    api_key = os.environ["RAPIDAPI_KEY"]
    host = os.environ.get("RAPIDAPI_JSEARCH_HOST", "jsearch.p.rapidapi.com")
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": host}
    params = {
        "query": f"{query} in {location}" if location else query,
        "page": "1",
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
    return data.get("data", [])


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
