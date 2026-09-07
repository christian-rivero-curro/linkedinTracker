"""
Automatizacion con Playwright de la busqueda de empleo de LinkedIn.

IMPORTANTE: los selectores de DOM usados aqui son los documentados/observados
a fecha de escritura de este modulo. LinkedIn cambia su HTML con cierta
frecuencia; si scrape_variant() deja de encontrar tarjetas o descripcion, este
es el primer sitio a revisar.

Timeouts por fase (en vez de un unico timeout generico reutilizado en todas
las fases, que mezclaba presupuestos de tiempo muy distintos):
  - COMMIT_TIMEOUT_MS: la respuesta HTTP inicial. Casi nunca tarda; si tarda
    esto, es un problema de red/DNS, no de LinkedIn tardando en renderizar.
  - DOMCONTENTLOADED_TIMEOUT_MS: que el HTML basico este listo.
  - RESULTS_SELECTOR_TIMEOUT_MS: que la app JS haya hidratado y pintado la
    lista de resultados.

Circuit breaker: si domcontentloaded no se alcanza a tiempo Y ademas no
aparece la lista de resultados, es una senal fuerte de que la app de LinkedIn
se quedo colgada en su pantalla de carga (sesion invalida/bloqueada) - no un
'0 resultados' legitimo. scrape_variant() lo distingue lanzando
LinkedInAppNotLoadedError en vez de devolver una lista vacia silenciosamente,
para que run_linkedin_scrape.py pueda cortar la ejecucion tras N fallos
seguidos en vez de repetir el mismo fallo lento en las 5 variantes.

Diagnostico: si la navegacion falla o se queda a medias, se guarda:
  - screenshot + titulo + HTML parcial (_save_diagnostics)
  - errores de consola JS del navegador
  - peticiones de red que fallaron
  - respuestas HTTP 401/403 de la API interna de LinkedIn (Voyager)
Todo esto se guarda en LINKEDIN_DIAGNOSTICS_DIR (por defecto
linkedin_diagnostics/, montado como volumen de lectura-escritura en
docker-compose.linkedin.yml).

Disenado para minimizar senales de bot:
- Reutiliza una sesion guardada (storage_state) en vez de loguearse cada vez.
- Delays aleatorios entre acciones (no fijos, para no ser un patron detectable).
- Se detiene INMEDIATAMENTE (LinkedInBlockedError) si detecta un checkpoint,
  authwall o redireccion a login - nunca reintenta en bucle sobre un bloqueo.

Nota Docker: Chromium necesita memoria compartida (/dev/shm) suficiente; el
default de Docker (64MB) suele quedarse corto. Por eso se lanza siempre con
--disable-dev-shm-usage, ademas de ampliar shm_size en docker-compose.linkedin.yml.

Nota sobre paginas: cada variante debe usar una pestana (page) NUEVA - ver
run_linkedin_scrape.py.
"""
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

STORAGE_STATE_PATH = os.environ.get("LINKEDIN_STORAGE_STATE", "linkedin_session/storage_state.json")
DIAGNOSTICS_DIR = os.environ.get("LINKEDIN_DIAGNOSTICS_DIR", "linkedin_diagnostics")

WORKPLACE_TYPE_MAP = {"remote": "2", "hybrid": "3", "onsite": "1"}

JOB_CARD_SELECTOR = "div.job-card-container, li.jobs-search-results__list-item"
TITLE_SELECTOR = "a.job-card-list__title, a.job-card-container__link, strong"
COMPANY_SELECTOR = ".artdeco-entity-lockup__subtitle, .job-card-container__company-name"
METADATA_SELECTOR = ".job-card-container__metadata-item, .artdeco-entity-lockup__caption"
DESCRIPTION_SELECTOR = "#job-details, .jobs-description__content, .jobs-box__html-content"
RESULTS_LIST_SELECTOR = "div.jobs-search-results-list, ul.jobs-search__results-list"

# Timeout general del contexto/acciones (clicks, selectors sueltos, etc.)
DEFAULT_ACTION_TIMEOUT_MS = 60000
# Timeouts especificos por fase de la navegacion (ver docstring del modulo)
COMMIT_TIMEOUT_MS = 20000
DOMCONTENTLOADED_TIMEOUT_MS = 45000
RESULTS_SELECTOR_TIMEOUT_MS = 15000
DESCRIPTION_TIMEOUT_MS = 8000

CHROMIUM_LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
]


class LinkedInBlockedError(Exception):
    """LinkedIn ha mostrado un checkpoint/authwall/login; hay que parar y NO reintentar en bucle."""


class LinkedInAppNotLoadedError(Exception):
    """
    La app de LinkedIn se quedo colgada en su pantalla de carga inicial: no se
    alcanzo domcontentloaded a tiempo Y tampoco aparecio la lista de
    resultados. A diferencia de un '0 resultados' legitimo (donde
    domcontentloaded si se alcanza y la app simplemente no tiene nada que
    mostrar), esto es una senal fuerte de sesion invalida/bloqueada - no debe
    tratarse como '0 ofertas para esta variante' sino como un fallo sistemico
    que justifica cortar la ejecucion (ver circuit breaker en
    run_linkedin_scrape.py).
    """


def _log(message: str):
    print(f"  [linkedin_scraper] {message}")


def _random_delay(min_s: float = 1.5, max_s: float = 4.0):
    time.sleep(random.uniform(min_s, max_s))


def _check_blocked(page):
    url = page.url
    if "/checkpoint/" in url or "/authwall" in url or url.rstrip("/").endswith("/login"):
        raise LinkedInBlockedError(f"LinkedIn redirigio a una pagina de bloqueo/login: {url}")


def attach_diagnostics_listeners(page) -> dict:
    """
    Engancha listeners a la pestana para capturar, en vivo, todo lo que puede
    explicar por que la app de LinkedIn se queda congelada en su pantalla de
    carga inicial ('app-loader'): errores de JS en consola, peticiones de red
    fallidas, y respuestas 401/403 de la API interna (Voyager).

    Devuelve un dict de listas que se van rellenando via closures; pasar este
    dict a scrape_variant()/_save_diagnostics() para volcarlo en los logs.
    """
    diag_state = {"console_errors": [], "failed_requests": [], "unauthorized_responses": []}

    def _on_console(msg):
        if msg.type in ("error", "warning"):
            diag_state["console_errors"].append(f"[{msg.type}] {msg.text}")

    def _on_request_failed(request):
        failure = request.failure
        diag_state["failed_requests"].append(f"{request.method} {request.url} -> {failure}")

    def _on_response(response):
        if response.status in (401, 403):
            diag_state["unauthorized_responses"].append(f"{response.status} {response.request.method} {response.url}")

    page.on("console", _on_console)
    page.on("requestfailed", _on_request_failed)
    page.on("response", _on_response)

    return diag_state


def _save_diagnostics(page, label: str, diag_state: dict | None = None):
    """Guarda screenshot + titulo + HTML parcial + (si se paso diag_state)
    errores de consola / peticiones fallidas / respuestas 401-403 capturadas
    durante la navegacion. Nunca lanza: un fallo capturando el diagnostico no
    debe tapar el error original."""
    try:
        os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)
        safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", label)[:50]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        screenshot_path = os.path.join(DIAGNOSTICS_DIR, f"{timestamp}_{safe_label}.png")
        page.screenshot(path=screenshot_path)
        _log(f"DIAGNOSTICO: screenshot guardado en {screenshot_path}")
        try:
            title = page.title()
        except Exception:
            title = "<no se pudo leer el titulo>"
        _log(f"DIAGNOSTICO: titulo de la pagina = {title!r}")
        _log(f"DIAGNOSTICO: URL actual = {page.url}")
        try:
            content_snippet = page.content()[:1500]
            _log(f"DIAGNOSTICO: primeros 1500 caracteres del HTML:\n{content_snippet}")
        except Exception as e:
            _log(f"DIAGNOSTICO: no se pudo leer el HTML: {e}")

        if diag_state is not None:
            unauthorized = diag_state.get("unauthorized_responses") or []
            if unauthorized:
                _log(f"DIAGNOSTICO: {len(unauthorized)} respuesta(s) 401/403 detectadas:")
                for line in unauthorized[-10:]:
                    _log(f"    {line}")
            else:
                _log("DIAGNOSTICO: no se detectaron respuestas 401/403.")

            failed = diag_state.get("failed_requests") or []
            if failed:
                _log(f"DIAGNOSTICO: {len(failed)} peticion(es) de red fallida(s):")
                for line in failed[-10:]:
                    _log(f"    {line}")
            else:
                _log("DIAGNOSTICO: no se detectaron peticiones de red fallidas.")

            console_errors = diag_state.get("console_errors") or []
            if console_errors:
                _log(f"DIAGNOSTICO: {len(console_errors)} error(es)/warning(s) de consola JS:")
                for line in console_errors[-10:]:
                    _log(f"    {line}")
            else:
                _log("DIAGNOSTICO: no se detectaron errores de consola JS.")
    except Exception as e:
        _log(f"DIAGNOSTICO: fallo capturando diagnostico: {e}")


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
        _log(f"Sesion cargada desde {STORAGE_STATE_PATH}")
    else:
        _log(f"AVISO: no existe {STORAGE_STATE_PATH}; se navegara SIN sesion (LinkedIn redirigira a login).")
    context = browser.new_context(**context_kwargs)
    context.set_default_navigation_timeout(DEFAULT_ACTION_TIMEOUT_MS)
    context.set_default_timeout(DEFAULT_ACTION_TIMEOUT_MS)
    return browser, context


def scrape_variant(page, query_text: str, location: str | None, remote_preference: str | None, hours_ago: int, max_jobs: int = 25, diag_state: dict | None = None) -> list[dict]:
    """
    Navega a la busqueda de LinkedIn para esta variante y devuelve una lista de
    dicts en el formato normalizado que espera pipeline/job_ingest.py.

    Lanza LinkedInAppNotLoadedError (en vez de devolver [] silenciosamente) si
    domcontentloaded no se alcanzo a tiempo Y tampoco aparecio la lista de
    resultados - senal fuerte de app colgada en el loader, distinta de un '0
    resultados' legitimo donde domcontentloaded si se completa.
    """
    url = build_search_url(query_text, location, remote_preference, hours_ago)
    _log(f"URL de busqueda: {url}")

    try:
        page.goto(url, wait_until="commit", timeout=COMMIT_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        _save_diagnostics(page, query_text, diag_state)
        raise TimeoutError(f"Timeout esperando 'commit' de la navegacion (>{COMMIT_TIMEOUT_MS}ms). Posible problema de red/DNS. Ultima URL alcanzada: {page.url}")
    _log(f"Commit recibido. URL tras el commit: {page.url}")

    dom_content_loaded_ok = True
    try:
        page.wait_for_load_state("domcontentloaded", timeout=DOMCONTENTLOADED_TIMEOUT_MS)
        _log("domcontentloaded alcanzado correctamente.")
    except PlaywrightTimeoutError:
        dom_content_loaded_ok = False
        _save_diagnostics(page, query_text, diag_state)
        _log("AVISO: domcontentloaded no se alcanzo a tiempo; se continua igualmente con el DOM parcial disponible.")

    _random_delay(2, 4)
    _check_blocked(page)

    try:
        page.wait_for_selector(RESULTS_LIST_SELECTOR, timeout=RESULTS_SELECTOR_TIMEOUT_MS)
        _log("Lista de resultados encontrada en el DOM.")
    except PlaywrightTimeoutError:
        _check_blocked(page)
        _save_diagnostics(page, query_text, diag_state)
        if not dom_content_loaded_ok:
            raise LinkedInAppNotLoadedError(
                "La app de LinkedIn no llego a hidratarse: domcontentloaded fallo y tampoco aparecio "
                "la lista de resultados. Probable sesion invalida/bloqueada, no una busqueda sin resultados."
            )
        _log(
            "AVISO: no se encontro el contenedor de resultados "
            f"(selector actual: '{RESULTS_LIST_SELECTOR}'). Puede que LinkedIn haya cambiado el HTML, "
            "o que la busqueda no tenga resultados. 0 ofertas para esta variante."
        )
        return []

    jobs = []
    seen_ids = set()
    scroll_attempts = 0
    skipped_no_id = 0

    while len(jobs) < max_jobs and scroll_attempts < 15:
        cards = page.query_selector_all(JOB_CARD_SELECTOR)
        _log(f"Scroll {scroll_attempts + 1}: {len(cards)} tarjetas visibles en el DOM (selector '{JOB_CARD_SELECTOR}'), {len(jobs)} unicas acumuladas hasta ahora.")
        for card in cards:
            if len(jobs) >= max_jobs:
                break
            job_id = card.get_attribute("data-job-id") or card.get_attribute("data-occludable-job-id")
            if not job_id:
                skipped_no_id += 1
                continue
            if job_id in seen_ids:
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
                    desc_el = page.wait_for_selector(DESCRIPTION_SELECTOR, timeout=DESCRIPTION_TIMEOUT_MS)
                    description = desc_el.inner_text().strip()
            except PlaywrightTimeoutError:
                _log(f"AVISO: no se pudo cargar la descripcion de '{title}' (selector '{DESCRIPTION_SELECTOR}' no encontrado a tiempo).")
            except LinkedInBlockedError:
                raise
            except Exception as e:
                _log(f"AVISO: error inesperado leyendo descripcion de '{title}': {e}")

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
            _log(f"Extraida: '{title}' - {company or 'empresa desconocida'} (id={job_id}, descripcion={len(description)} caracteres)")
            _random_delay(0.8, 2.0)

        if len(jobs) >= max_jobs:
            break

        page.mouse.wheel(0, 1200)
        _random_delay(1.5, 3.0)
        scroll_attempts += 1

    if skipped_no_id:
        _log(f"AVISO: {skipped_no_id} tarjetas sin atributo data-job-id/data-occludable-job-id, ignoradas (posible selector desactualizado).")
    _log(f"Total extraido para esta variante: {len(jobs)} ofertas.")

    return jobs
