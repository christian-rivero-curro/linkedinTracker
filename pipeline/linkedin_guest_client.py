"""
Cliente HTTP para interactuar con la API pública / guest de LinkedIn.

Implementado con altos estándares de resiliencia y fiabilidad:
- Reintentos exponenciales con jitter (Full Jitter) ante errores de red, timeouts y 429.
- Respeto de cabecera 'Retry-After' en rate limits.
- Timeouts diferenciados (connect, read, write, pool) y pool de conexiones seguro.
- Detección de authwall / checkpoint / captchas en el contenido HTML.
- Circuit breaker ante bloqueos consecutivos para no quemar la IP.
- Limpieza y sanitización profunda del HTML (eliminación de scripts, normalización Unicode).
- Parseo defensivo y multilingüe de fechas relativas (español e inglés).
"""
import logging
import random
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("linkedin_guest_client")

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
]

BASE_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
BASE_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

WORKPLACE_TYPE_MAP = {
    "onsite": "1",
    "remote": "2",
    "hybrid": "3",
}

# Errores de red transitorios recuperables
RETRYABLE_NETWORK_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
)

# Códigos de estado HTTP recuperables
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class LinkedInClientError(Exception):
    """Excepción base del cliente de LinkedIn Guest."""


class LinkedInRateLimitError(LinkedInClientError):
    """Excedido el límite de peticiones (HTTP 429) tras reintentos."""


class LinkedInBlockedError(LinkedInClientError):
    """LinkedIn ha mostrado un checkpoint / authwall / CAPTCHA."""


def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def build_search_url(
    query_text: str,
    location: str | None = None,
    remote_preference: str | None = None,
    hours_ago: int = 4,
    start: int = 0,
) -> str:
    params = {
        "keywords": (query_text or "").strip(),
        "start": max(0, int(start)),
    }
    if location and location.strip():
        params["location"] = location.strip()

    if hours_ago > 0:
        params["f_TPR"] = f"r{int(hours_ago * 3600)}"

    if remote_preference and remote_preference.strip():
        workplace_val = WORKPLACE_TYPE_MAP.get(remote_preference.lower().strip())
        if workplace_val:
            params["f_WT"] = workplace_val

    return f"{BASE_SEARCH_URL}?{urlencode(params)}"


def _clean_text(text: str | None) -> str:
    """Normaliza espacios en blanco y caracteres Unicode preservando párrafos limpios."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.splitlines()]
    cleaned_lines = []
    prev_empty = False
    for line in lines:
        if line:
            cleaned_lines.append(line)
            prev_empty = False
        elif not prev_empty:
            cleaned_lines.append("")
            prev_empty = True
    return "\n".join(cleaned_lines).strip()


def _is_authwall_or_checkpoint(html_text: str, current_url: str) -> bool:
    """Verifica si la respuesta HTTP corresponde a un checkpoint, captcha o authwall."""
    if not html_text:
        return False
    lowered_url = (current_url or "").lower()
    if "/checkpoint/" in lowered_url or "/authwall" in lowered_url:
        return True

    lowered_html = html_text[:3000].lower()
    indicators = [
        "security verification",
        "verificación de seguridad",
        "recaptcha",
        "checkpoint/challenge",
        "authwall?trk=",
        "unusual traffic from your computer",
    ]
    return any(ind in lowered_html for ind in indicators)


def _parse_relative_posted_at(text_value: str | None) -> datetime | None:
    """
    Parseo defensivo multilingüe (español e inglés) para fechas relativas.
    Nunca lanza excepción.
    """
    if not text_value:
        return None
    try:
        lowered = text_value.lower().strip()
        now = datetime.now(timezone.utc)

        # Expresiones inmediatas
        if any(w in lowered for w in ("recién", "just now", "momento", "moment")):
            return now

        # Patrones tipo "hace X horas", "X hours ago", "hace 1 día"
        match = re.search(r"(\d+)\s*(minuto|hora|d[ii]a|semana|mes|minute|hour|day|week|month|min|hr|h|d|w|mo)s?", lowered)
        if not match:
            return None

        amount = int(match.group(1))
        unit = match.group(2)

        if "min" in unit:
            return now - timedelta(minutes=amount)
        if "hor" in unit or "hour" in unit or unit == "h" or unit == "hr":
            return now - timedelta(hours=amount)
        if "d" in unit:
            return now - timedelta(days=amount)
        if "seman" in unit or "week" in unit or unit == "w":
            return now - timedelta(weeks=amount)
        if "mes" in unit or "month" in unit or unit == "mo":
            return now - timedelta(days=amount * 30)
    except Exception as e:
        logger.debug(f"No se pudo parsear fecha relativa '{text_value}': {e}")
    return None


def _detect_remote_type(text_snippet: str | None) -> str | None:
    if not text_snippet:
        return None
    lowered = text_snippet.lower()
    if "remoto" in lowered or "remote" in lowered:
        return "remote"
    if "hibrido" in lowered or "híbrido" in lowered or "hybrid" in lowered:
        return "hybrid"
    if "presencial" in lowered or "on-site" in lowered or "onsite" in lowered:
        return "onsite"
    return None


class LinkedInGuestClient:
    """
    Cliente robusto para LinkedIn Guest API con gestión de sesión HTTP,
    reintentos exponenciales y circuit breaker de seguridad.
    """

    def __init__(
        self,
        timeout: float = 20.0,
        max_retries: int = 3,
        circuit_breaker_threshold: int = 3,
    ):
        self.timeout_config = httpx.Timeout(
            timeout=timeout,
            connect=10.0,
            read=25.0,
            write=10.0,
            pool=10.0,
        )
        self.max_retries = max(1, max_retries)
        self.circuit_breaker_threshold = max(1, circuit_breaker_threshold)
        self.consecutive_blocks = 0
        self.client = self._init_client()

    def _init_client(self) -> httpx.Client:
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        return httpx.Client(
            timeout=self.timeout_config,
            limits=limits,
            follow_redirects=True,
        )

    def _recreate_client(self):
        """Re-inicializa el cliente HTTP para descartar sockets dañados tras fallos severos."""
        try:
            self.client.close()
        except Exception:
            pass
        self.client = self._init_client()

    def close(self):
        try:
            self.client.close()
        except Exception as e:
            logger.debug(f"Error cerrando cliente HTTP: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _calculate_backoff(self, attempt: int, is_rate_limit: bool = False, retry_after: str | None = None) -> float:
        """Calcula el tiempo de espera con Full Jitter exponencial."""
        if retry_after:
            try:
                seconds = float(retry_after)
                if 0 < seconds <= 120:
                    return seconds + random.uniform(1.0, 3.0)
            except (ValueError, TypeError):
                pass

        if is_rate_limit:
            # Backoff más amplio para 429
            base = 12.0 * (1.8 ** attempt)
            max_wait = 90.0
        else:
            # Backoff para timeouts o 5xx
            base = 2.0 * (2.0 ** attempt)
            max_wait = 30.0

        delay = min(max_wait, base)
        jitter = random.uniform(0.5, 2.5)
        return delay + jitter

    def _get_with_retry(self, url: str) -> httpx.Response | None:
        """
        Realiza petición GET con reintentos exponenciales, jitter y manejo de rate limits.
        Lanza LinkedInRateLimitError o LinkedInBlockedError si se alcanzan umbrales críticos.
        """
        if self.consecutive_blocks >= self.circuit_breaker_threshold:
            raise LinkedInBlockedError(
                f"Circuit breaker activo: {self.consecutive_blocks} bloqueos/429 consecutivos detectados. "
                "Deteniendo para proteger la reputación de red."
            )

        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.get(url, headers=_get_headers())

                # Verificación de authwall / captcha en la respuesta
                if _is_authwall_or_checkpoint(resp.text, str(resp.url)):
                    self.consecutive_blocks += 1
                    logger.warning(f"Authwall / Checkpoint detectado en respuesta a {url}")
                    if self.consecutive_blocks >= self.circuit_breaker_threshold:
                        raise LinkedInBlockedError(f"LinkedIn activó Authwall/Checkpoint en {url}")
                    time.sleep(random.uniform(5.0, 10.0))
                    continue

                if resp.status_code == 200:
                    # Éxito: resetea contador de bloqueos consecutivos
                    self.consecutive_blocks = 0
                    return resp

                if resp.status_code == 429:
                    self.consecutive_blocks += 1
                    retry_after = resp.headers.get("Retry-After")
                    wait_time = self._calculate_backoff(attempt, is_rate_limit=True, retry_after=retry_after)
                    logger.warning(
                        f"HTTP 429 Too Many Requests (intento {attempt + 1}/{self.max_retries + 1}). "
                        f"Esperando {wait_time:.1f}s antes de reintentar..."
                    )
                    time.sleep(wait_time)
                    continue

                if resp.status_code in (404, 410):
                    # Oferta eliminada o no encontrada; no se debe reintentar
                    return None

                if resp.status_code in (401, 403):
                    self.consecutive_blocks += 1
                    logger.warning(f"HTTP {resp.status_code} Forbidden/Unauthorized en {url}")
                    if self.consecutive_blocks >= self.circuit_breaker_threshold:
                        raise LinkedInBlockedError(f"LinkedIn devolvió HTTP {resp.status_code} de forma persistente.")
                    time.sleep(random.uniform(4.0, 8.0))
                    continue

                if resp.status_code in RETRYABLE_STATUS_CODES:
                    wait_time = self._calculate_backoff(attempt, is_rate_limit=False)
                    logger.warning(f"HTTP {resp.status_code} en {url}. Reintentando en {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue

                # Otro código no recuperable
                logger.warning(f"HTTP inesperado {resp.status_code} para {url}")
                return None

            except RETRYABLE_NETWORK_EXCEPTIONS as ne:
                last_error = ne
                wait_time = self._calculate_backoff(attempt, is_rate_limit=False)
                logger.warning(
                    f"Fallo de red ({type(ne).__name__}: {ne}) al conectar con {url}. "
                    f"Reintentando en {wait_time:.1f}s (intento {attempt + 1}/{self.max_retries + 1})..."
                )
                self._recreate_client()
                time.sleep(wait_time)

            except (LinkedInBlockedError, LinkedInRateLimitError):
                raise

            except Exception as e:
                last_error = e
                logger.warning(f"Error inesperado ({type(e).__name__}) en GET {url}: {e}")
                self._recreate_client()
                time.sleep(random.uniform(2.0, 4.0))

        if self.consecutive_blocks >= self.circuit_breaker_threshold:
            raise LinkedInRateLimitError(f"Límite de peticiones o bloqueos excedido para {url}: {last_error}")

        logger.error(f"Agotados los reintentos ({self.max_retries}) para {url}. Último error: {last_error}")
        return None

    def fetch_job_listings(
        self,
        query_text: str,
        location: str | None = None,
        remote_preference: str | None = None,
        hours_ago: int = 4,
        max_jobs: int = 25,
    ) -> list[dict]:
        listings = []
        seen_ids = set()
        start = 0
        page_size = 25

        while len(listings) < max_jobs:
            url = build_search_url(
                query_text=query_text,
                location=location,
                remote_preference=remote_preference,
                hours_ago=hours_ago,
                start=start,
            )

            try:
                resp = self._get_with_retry(url)
            except LinkedInClientError:
                raise
            except Exception as e:
                logger.error(f"Fallo irrecuperable en listado de búsqueda ({url}): {e}")
                break

            if not resp or not resp.text.strip():
                break

            try:
                soup = BeautifulSoup(resp.text, "html.parser")
            except Exception as e:
                logger.error(f"Error de parsing HTML en listado: {e}")
                break

            cards = soup.find_all("li")
            if not cards:
                break

            found_in_page = 0
            for card in cards:
                try:
                    base_card = card.find("div", class_=lambda c: c and "base-card" in c)
                    urn = base_card.get("data-entity-urn") if base_card else None
                    job_id = None
                    if urn and ":" in urn:
                        job_id = urn.split(":")[-1].strip()

                    link_el = card.find("a", class_=lambda c: c and "base-card__full-link" in c)
                    link_href = link_el.get("href") if link_el else None

                    if not job_id and link_href:
                        match = re.search(r"/jobs/view/.*?([0-9]{8,})", link_href)
                        if match:
                            job_id = match.group(1)

                    if not job_id or not job_id.isdigit() or job_id in seen_ids:
                        continue

                    seen_ids.add(job_id)

                    title_el = card.find("h3", class_=lambda c: c and "base-search-card__title" in c)
                    title = _clean_text(title_el.get_text()) if title_el else "Sin título"

                    company_el = card.find("h4", class_=lambda c: c and "base-search-card__subtitle" in c)
                    company = _clean_text(company_el.get_text()) if company_el else None

                    loc_el = card.find("span", class_=lambda c: c and "job-search-card__location" in c)
                    loc_text = _clean_text(loc_el.get_text()) if loc_el else None

                    time_el = card.find("time")
                    posted_at = None
                    if time_el:
                        dt_attr = time_el.get("datetime")
                        if dt_attr:
                            try:
                                posted_at = datetime.fromisoformat(dt_attr.strip()).replace(tzinfo=timezone.utc)
                            except Exception:
                                posted_at = None
                        if not posted_at:
                            posted_at = _parse_relative_posted_at(time_el.get_text())

                    listings.append({
                        "job_id": job_id,
                        "title": title,
                        "company": company,
                        "location": loc_text,
                        "apply_link": f"https://www.linkedin.com/jobs/view/{job_id}/",
                        "posted_at": posted_at or datetime.now(timezone.utc),
                    })
                    found_in_page += 1
                    if len(listings) >= max_jobs:
                        break

                except Exception as card_err:
                    logger.debug(f"Error extrayendo datos de tarjeta individual: {card_err}")
                    continue

            if found_in_page == 0:
                break

            start += page_size
            time.sleep(random.uniform(1.2, 2.5))

        return listings

    def fetch_job_detail(self, job_id: str) -> dict | None:
        if not job_id or not str(job_id).isdigit():
            logger.warning(f"job_id inválido descartado: {job_id}")
            return None

        url = BASE_DETAIL_URL.format(job_id=job_id)
        try:
            resp = self._get_with_retry(url)
        except LinkedInClientError:
            raise
        except Exception as e:
            logger.error(f"Error descargando detalle de oferta {job_id}: {e}")
            return None

        if not resp or not resp.text.strip():
            return None

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            logger.error(f"Error parseando HTML para oferta {job_id}: {e}")
            return None

        # Eliminar elementos no textuales antes de extraer descripción
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()

        # Título
        title_el = soup.find("h2", class_=lambda c: c and "top-card-layout__title" in c)
        title = _clean_text(title_el.get_text()) if title_el else None

        # Empresa
        company_el = soup.find("a", class_=lambda c: c and "topcard__org-name-link" in c) or soup.find(
            "span", class_=lambda c: c and "topcard__flavor" in c
        )
        company = _clean_text(company_el.get_text()) if company_el else None

        # Ubicación
        loc_el = soup.find("span", class_=lambda c: c and "topcard__flavor--bullet" in c)
        location = _clean_text(loc_el.get_text()) if loc_el else None

        # Fecha de publicación
        time_el = soup.find("span", class_=lambda c: c and "posted-time-ago" in c)
        posted_at = _parse_relative_posted_at(time_el.get_text()) if time_el else None

        # Descripción completa del puesto
        desc_el = soup.find("div", class_=lambda c: c and "show-more-less-html__markup" in c)
        if not desc_el:
            desc_el = soup.find("section", class_=lambda c: c and "description" in c)
        if not desc_el:
            desc_el = soup.find("div", class_=lambda c: c and "decoratedJobPosting" in c)

        raw_desc = desc_el.get_text(separator="\n") if desc_el else ""
        description = _clean_text(raw_desc)

        # Criterios del puesto
        criteria_parts = []
        try:
            criteria_items = soup.find_all("li", class_=lambda c: c and "description__job-criteria-item" in c)
            for item in criteria_items:
                h = item.find("h3")
                v = item.find("span")
                if h and v:
                    header_text = _clean_text(h.get_text())
                    val_text = _clean_text(v.get_text())
                    if header_text and val_text:
                        criteria_parts.append(f"{header_text}: {val_text}")
        except Exception as ce:
            logger.debug(f"Error parseando criterios para {job_id}: {ce}")

        if criteria_parts:
            criteria_block = "\n[Criterios del puesto]\n" + "\n".join(criteria_parts)
            description = f"{description}\n{criteria_block}".strip()

        remote_snippet = f"{title or ''} {location or ''} {' '.join(criteria_parts)} {description[:500]}"
        detected_remote = _detect_remote_type(remote_snippet)

        return {
            "job_id": job_id,
            "title": title,
            "company": company,
            "location": location,
            "remote_type": detected_remote,
            "description": description,
            "posted_at": posted_at,
        }

    def scrape_variant(
        self,
        query_text: str,
        location: str | None = None,
        remote_preference: str | None = None,
        hours_ago: int = 4,
        max_jobs: int = 25,
    ) -> list[dict]:
        clean_query = (query_text or "").strip()
        logger.info(
            f"Buscando '{clean_query}' en '{location or 'cualquiera'}' "
            f"(modalidad: {remote_preference or 'cualquiera'}, ventana: {hours_ago}h, máx: {max_jobs})"
        )

        listings = self.fetch_job_listings(
            query_text=clean_query,
            location=location,
            remote_preference=remote_preference,
            hours_ago=hours_ago,
            max_jobs=max_jobs,
        )

        logger.info(f"Encontradas {len(listings)} ofertas preliminares en listado. Extrayendo descripciones...")

        jobs = []
        for idx, item in enumerate(listings):
            job_id = item["job_id"]
            # Pausa educada y aleatoria entre peticiones de detalle
            time.sleep(random.uniform(0.8, 1.8))

            detail = None
            try:
                detail = self.fetch_job_detail(job_id)
            except (LinkedInBlockedError, LinkedInRateLimitError):
                raise
            except Exception as de:
                logger.warning(f"No se pudo obtener detalle para {job_id}: {de}")

            title = (detail and detail.get("title")) or item.get("title") or "Sin título"
            company = (detail and detail.get("company")) or item.get("company")
            location_val = (detail and detail.get("location")) or item.get("location")
            description = (detail and detail.get("description")) or ""
            remote_type = (detail and detail.get("remote_type")) or _detect_remote_type(f"{title} {location_val}")
            posted_at = (detail and detail.get("posted_at")) or item.get("posted_at") or datetime.now(timezone.utc)

            job_dict = {
                "external_id": f"linkedin_{job_id}",
                "title": title,
                "company": company,
                "location": location_val,
                "remote_type": remote_type,
                "description": description,
                "apply_link": f"https://www.linkedin.com/jobs/view/{job_id}/",
                "source": "linkedin",
                "salary_min": None,
                "salary_max": None,
                "posted_at": posted_at.isoformat() if isinstance(posted_at, datetime) else str(posted_at),
            }
            jobs.append(job_dict)
            logger.info(f"  [{idx+1}/{len(listings)}] '{title}' - {company or 'empresa desconocida'} ({len(description)} chars desc)")

        return jobs
