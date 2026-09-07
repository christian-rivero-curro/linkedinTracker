"""
Automatizacion con Playwright de la busqueda de empleo de LinkedIn.

IMPORTANTE: los selectores de DOM usados aqui son los documentados/observados
a fecha de escritura de este modulo. LinkedIn cambia su HTML con cierta
frecuencia; si scrape_variant() deja de encontrar tarjetas o descripcion, este
es el primer sitio a revisar (usa el inspector del navegador sobre una
busqueda real para actualizar los selectores).

Disenado para minimizar senales de bot:
- Reutiliza una sesion guardada (storage_state) en vez de loguearse cada vez.
- Delays aleatorios entre acciones (no fijos, para no ser un patron detectable).
- Se detiene INMEDIATAMENTE (LinkedInBlockedError) si detecta un checkpoint,
  authwall o redireccion a login - nunca reintenta en bucle sobre un bloqueo.

Nota Docker: Chromium necesita memoria compartida (/dev/shm) suficiente; el
default de Docker (64MB) suele quedarse corto y el renderer se cuelga sin dar
error claro (page.goto revienta en timeout). Por eso se lanza siempre con
--disable-dev-shm-usage (usa /tmp en su lugar), ademas de ampliar shm_size en
docker-compose.linkedin.yml como margen extra.
"""
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

STORAGE_STATE_PATH = os.environ.get("LINKEDIN_STORAGE_STATE", "linkedin_session/storage_state.json")

WORKPLACE_TYPE_MAP = {"remote": "2", "hybrid": "3", "onsite": "1"}

JOB_CARD_SELECTOR = "div.job-card-container, li.jobs-search-results__list-item"
TITLE_SELECTOR = "a.job-card-list__title, a.job-card-container__link, strong"
COMPANY_SELECTOR = ".artdeco-entity-lockup__subtitle, .job-card-container__company-name"
METADATA_SELECTOR = ".job-card-container__metadata-item, .artdeco-entity-lockup__caption"
DESCRIPTION_SELECTOR = "#job-details, .jobs-description__content, .jobs-box__html-content"
RESULTS_LIST_SELECTOR = "div.jobs-search-results-list, ul.jobs-search__results-list"

NAVIGATION_TIMEOUT_MS = 60000

CHROMIUM_LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
]


class LinkedInBlockedError(Exception):
    """LinkedIn ha mostrado un checkpoint/authwall/login; hay que parar y NO reintentar en bucle."""


def _random_delay(min_s: float = 1.5, max_s: float = 4.0):
    time.sleep(random.uniform(min_s, max_s))


def _check_blocked(page):
    url = page.url
    if "/checkpoint/" in url or "/authwall" in url or url.rstrip("/").endswith("/login"):
        raise LinkedInBlockedError(f"LinkedIn redirigio a una pagina de bloqueo/login: {url}")


def build_search_url(query_text: str, location: str | None, remote_preference: str | None, hours_ago: int) -> str:
    params = {"keywords": query_text}
    if location:
        params["location"] = location
    params["f_TPR"] = f"r{int(hours_ago * 3600)}"
    workplace_type = WORKPLACE_TYPE_MAP.get((remote_preference or "").lower())
    if workplace_type:
        params["f_WT"] = workplace_type
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


def _parse_relative_posted_at(text_value: str | None):
    """Best-effort: convierte 'Hace 3 horas' / '2 days ago' / '45 minutos' en
    datetime UTC. Si no reconoce el formato, devuelve None (no critico, ya que
    f_TPR garantiza la ventana temporal server-side)."""
    if not text_value:
        return None
    text_value = text_value.lower()
    match = re.search(r"(\d+)\s*(minuto|hora|d[ii]a|minute|hour|day)", text_value)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    now = datetime.now(timezone.utc)
    if "minut" in unit:
        return now - timedelta(minutes=amount)
    if "hora" in unit or "hour" in unit:
        return now - timedelta(hours=amount)
    if "d" in unit:
        return now - timedelta(days=amount)
    return None


def _detect_remote_type(metadata_text: str | None) -> str | None:
    if not metadata_text:
        return None
    lowered = metadata_text.lower()
    if "remoto" in lowered or "remote" in lowered:
        return "remote"
    if "hibrido" in lowered or "hybrid" in lowered:
        return "hybrid"
    if "presencial" in lowered or "on-site" in lowered or "onsite" in lowered:
        return "onsite"
    return None


def new_browser_context(playwright, headless: bool = True):
    browser = playwright.chromium.launch(headless=headless, args=CHROMIUM_LAUNCH_ARGS)
    context_kwargs = {"viewport": {"width": 1366, "height": 900}}
    if os.path.exists(STORAGE_STATE_PATH):
        context_kwargs["storage_state"] = STORAGE_STATE_PATH
    context = browser.new_context(**context_kwargs)
    context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
    context.set_default_timeout(NAVIGATION_TIMEOUT_MS)
    return browser, context


def scrape_variant(page, query_text: str, location: str | None, remote_preference: str | None, hours_ago: int, max_jobs: int = 25) -> list[dict]:
    """
    Navega a la busqueda de LinkedIn para esta variante y devuelve una lista de
    dicts en el formato normalizado que espera pipeline/job_ingest.py.
    """
    url = build_search_url(query_text, location, remote_preference, hours_ago)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        raise TimeoutError(f"Timeout navegando a LinkedIn. Ultima URL alcanzada: {page.url}")
    _random_delay(2, 4)
    _check_blocked(page)

    try:
        page.wait_for_selector(RESULTS_LIST_SELECTOR, timeout=15000)
    except PlaywrightTimeoutError:
        _check_blocked(page)
        return []

    jobs = []
    seen_ids = set()
    scroll_attempts = 0

    while len(jobs) < max_jobs and scroll_attempts < 15:
        cards = page.query_selector_all(JOB_CARD_SELECTOR)
        for card in cards:
            if len(jobs) >= max_jobs:
                break
            job_id = card.get_attribute("data-job-id") or card.get_attribute("data-occludable-job-id")
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            title_el = card.query_selector(TITLE_SELECTOR)
            company_el = card.query_selector(COMPANY_SELECTOR)
            metadata_el = card.query_selector(METADATA_SELECTOR)

            title = title_el.inner_text().strip() if title_el else "Sin titulo"
            company = company_el.inner_text().strip() if company_el else None
            metadata_text = metadata_el.inner_text().strip() if metadata_el else None

            description = ""
            try:
                if title_el:
                    title_el.click()
                    _random_delay(1.5, 3.5)
                    _check_blocked(page)
                    desc_el = page.wait_for_selector(DESCRIPTION_SELECTOR, timeout=8000)
                    description = desc_el.inner_text().strip()
            except PlaywrightTimeoutError:
                pass
            except LinkedInBlockedError:
                raise
            except Exception:
                pass

            posted_at = _parse_relative_posted_at(metadata_text) or datetime.now(timezone.utc)

            jobs.append({
                "external_id": f"linkedin_{job_id}",
                "title": title,
                "company": company,
                "location": metadata_text,
                "remote_type": _detect_remote_type(metadata_text),
                "description": description,
                "apply_link": f"https://www.linkedin.com/jobs/view/{job_id}/",
                "source": "linkedin",
                "salary_min": None,
                "salary_max": None,
                "posted_at": posted_at.isoformat(),
            })
            _random_delay(0.8, 2.0)

        if len(jobs) >= max_jobs:
            break

        page.mouse.wheel(0, 1200)
        _random_delay(1.5, 3.0)
        scroll_attempts += 1

    return jobs
