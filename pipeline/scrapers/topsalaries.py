"""
Implementación del scraper para TopSalaries (https://topsalaries.tech/).
Consulta la API REST pública nativa para vacantes remotas de alta remuneración (6 cifras).
Aplica filtrado en 2 pasos:
  1. Descarga el catálogo general en una sola petición.
  2. Filtra por variantes del usuario y recupera el detalle de los matches con apply_url directo.
"""
import logging
import time
from typing import Any
import httpx

from pipeline.scrapers.base import BaseJobScraper
from pipeline.job_ingest import process_and_store_job

logger = logging.getLogger("scrapers.topsalaries")

BASE_URL = "https://topsalaries.tech/api"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class TopSalariesScraper(BaseJobScraper):
    source_id = "topsalaries"
    source_name = "TopSalaries"
    description = "Plataforma de vacantes remotas internacionales con salarios transparentes de 6 cifras."
    is_available = True
    badge_status = "active"
    badge_label = "Activo"
    icon = "💎"

    def __init__(self, delay_between_details: float = 0.25):
        self.delay_between_details = delay_between_details

    def scrape_user(
        self,
        engine,
        user_id: int,
        profile: dict,
        variants: list[dict],
        **kwargs: Any,
    ) -> dict[str, Any]:
        active_variants = [v for v in variants if v.get("is_active", True)]
        if not active_variants:
            return {
                "source": self.source_id,
                "found": 0,
                "inserted": 0,
                "duplicates": 0,
                "errors": ["No hay variantes de búsqueda activas para este usuario."],
                "stats_per_variant": [],
            }

        total_found = 0
        total_inserted = 0
        total_duplicates = 0
        errors: list[str] = []
        stats: list[dict] = []

        headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}

        # 1. Obtener catálogo general de ofertas
        try:
            with httpx.Client(headers=headers, follow_redirects=True, timeout=15.0) as client:
                resp = client.get(f"{BASE_URL}/jobs")
                if resp.status_code != 200:
                    msg = f"TopSalaries API devolvió status {resp.status_code}"
                    errors.append(msg)
                    logger.error(msg)
                    return {
                        "source": self.source_id,
                        "found": 0,
                        "inserted": 0,
                        "duplicates": 0,
                        "errors": errors,
                        "stats_per_variant": [],
                    }
                catalog = resp.json()
        except Exception as e:
            msg = f"Error conectando a TopSalaries API: {e}"
            errors.append(msg)
            logger.error(msg)
            return {
                "source": self.source_id,
                "found": 0,
                "inserted": 0,
                "duplicates": 0,
                "errors": errors,
                "stats_per_variant": [],
            }

        if not isinstance(catalog, list):
            msg = "El formato devuelto por TopSalaries no es una lista."
            errors.append(msg)
            return {
                "source": self.source_id,
                "found": 0,
                "inserted": 0,
                "duplicates": 0,
                "errors": errors,
                "stats_per_variant": [],
            }

        logger.info(f"TopSalaries: {len(catalog)} ofertas activas obtenidas del catálogo.")

        # Cache en memoria para detalles ya consultados en esta corrida
        details_cache: dict[str, dict] = {}

        # 2. Procesar variantes del usuario
        with httpx.Client(headers=headers, follow_redirects=True, timeout=12.0) as client:
            for variant in active_variants:
                q_text = variant["query_text"].strip()
                v_id = variant["id"]
                terms = [t.lower() for t in q_text.split() if len(t) > 2]

                v_stat = {
                    "id": v_id,
                    "query": q_text,
                    "found": 0,
                    "inserted": 0,
                    "duplicates": 0,
                    "status": "OK",
                }

                # Buscar coincidencias en catálogo para esta variante
                matched_entries = []
                for item in catalog:
                    title = (item.get("title") or "").lower()
                    company = (item.get("company") or "").lower()
                    category = " ".join(item.get("category") or []).lower()
                    tags = " ".join(item.get("tags") or []).lower()
                    haystack = f"{title} {company} {category} {tags}"

                    # Si coincide la frase completa o al menos el término principal
                    if q_text.lower() in haystack or (terms and all(t in haystack for t in terms)):
                        matched_entries.append(item)

                v_stat["found"] = len(matched_entries)
                total_found += len(matched_entries)
                logger.info(f"Variante '{q_text}': {len(matched_entries)} coincidencia(s) en TopSalaries.")

                inserted_this = 0
                duplicates_this = 0

                for item in matched_entries:
                    slug = item.get("job_detail_id")
                    if not slug:
                        continue

                    # Obtener detalle para extraer apply_url real y descripción completa
                    if slug not in details_cache:
                        try:
                            time.sleep(self.delay_between_details)
                            det_resp = client.get(f"{BASE_URL}/jobs/{slug}")
                            if det_resp.status_code == 200:
                                details_cache[slug] = det_resp.json()
                            else:
                                details_cache[slug] = item
                        except Exception as det_err:
                            logger.warning(f"No se pudo obtener detalle de '{slug}': {det_err}")
                            details_cache[slug] = item

                    detail = details_cache.get(slug) or item

                    # Construir descripción comprensiva
                    parts = []
                    if detail.get("overview"):
                        parts.append(f"Resumen:\n{detail['overview']}")
                    if detail.get("description"):
                        parts.append(f"Sobre la empresa:\n{detail['description']}")
                    if detail.get("skills"):
                        parts.append(f"Requisitos:\n{detail['skills']}")
                    if detail.get("responsibilities"):
                        parts.append(f"Responsabilidades:\n{detail['responsibilities']}")
                    if detail.get("benefits"):
                        parts.append(f"Beneficios:\n{detail['benefits']}")

                    full_desc = "\n\n".join(parts) if parts else (item.get("description") or item.get("title") or "")

                    # Formato de salario
                    currency = item.get("currency") or "$"
                    sal_min = item.get("salary_lower")
                    sal_max = item.get("salary")
                    salary_raw = None
                    if sal_min and sal_max:
                        salary_raw = f"{currency}{sal_min:,} - {currency}{sal_max:,}"
                    elif sal_max:
                        salary_raw = f"{currency}{sal_max:,}"

                    job_external_id = f"topsalaries_{item.get('id') or slug}"
                    apply_link = detail.get("apply_url") or item.get("url") or f"https://topsalaries.tech/job-details/{slug}"

                    canonical_job = {
                        "external_id": job_external_id,
                        "title": item.get("title") or "Sin título",
                        "company": item.get("company"),
                        "location": item.get("location"),
                        "remote_type": "remote",
                        "description": full_desc,
                        "apply_link": apply_link,
                        "source": "topsalaries",
                        "salary_min": sal_min,
                        "salary_max": sal_max,
                        "salary_raw": salary_raw,
                        "posted_at": item.get("postedDate"),
                    }

                    try:
                        with engine.begin() as conn:
                            with conn.begin_nested():
                                _, _, was_inserted = process_and_store_job(
                                    conn=conn,
                                    job=canonical_job,
                                    profile=profile,
                                    cutoff=None,
                                    errors=errors,
                                    variant_id=v_id,
                                    allowed_sources=["topsalaries"],
                                    verbose=False,
                                )
                        if was_inserted:
                            inserted_this += 1
                            total_inserted += 1
                            logger.info(f"  [+] INSERTADA (TopSalaries): '{canonical_job['title']}' - {canonical_job['company']}")
                        else:
                            duplicates_this += 1
                            total_duplicates += 1
                    except Exception as ins_err:
                        err_msg = f"Error guardando job {job_external_id}: {ins_err}"
                        errors.append(err_msg)
                        logger.error(err_msg)

                v_stat["inserted"] = inserted_this
                v_stat["duplicates"] = duplicates_this
                stats.append(v_stat)

        return {
            "source": self.source_id,
            "found": total_found,
            "inserted": total_inserted,
            "duplicates": total_duplicates,
            "errors": errors,
            "stats_per_variant": stats,
        }
