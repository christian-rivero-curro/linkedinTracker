"""
Implementación del scraper de LinkedIn Guest API adaptado a BaseJobScraper.
Extrae ofertas públicas sin necesidad de login ni tokens de pago.
"""
import logging
import os
from typing import Any

from pipeline.scrapers.base import BaseJobScraper
from pipeline.linkedin_guest_client import (
    LinkedInGuestClient,
    LinkedInRateLimitError,
    LinkedInBlockedError,
)
from pipeline.job_ingest import process_and_store_job

logger = logging.getLogger("scrapers.linkedin")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


class LinkedInScraper(BaseJobScraper):
    source_id = "linkedin"
    source_name = "LinkedIn"
    description = "Portal profesional global con ofertas públicas de empleo vía Guest API."
    is_available = True
    badge_status = "active"
    badge_label = "Activo"
    icon = "🔵"

    def __init__(self, hours_ago: int | None = None, max_jobs_per_variant: int | None = None):
        self.hours_ago = hours_ago or max(1, _int_env("LINKEDIN_HOURS_AGO", 4))
        self.max_jobs_per_variant = max_jobs_per_variant or max(1, _int_env("LINKEDIN_MAX_JOBS_PER_VARIANT", 25))

    def scrape_user(
        self,
        engine,
        user_id: int,
        profile: dict,
        variants: list[dict],
        **kwargs: Any,
    ) -> dict[str, Any]:
        location = profile.get("location_preference")
        remote_pref = profile.get("remote_preference")

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

        with LinkedInGuestClient() as client:
            for v in active_variants:
                q_text = v["query_text"]
                v_id = v["id"]
                v_stat = {
                    "id": v_id,
                    "query": q_text,
                    "found": 0,
                    "inserted": 0,
                    "duplicates": 0,
                    "status": "OK",
                }

                try:
                    raw_jobs = client.scrape_variant(
                        query_text=q_text,
                        location=location,
                        remote_preference=remote_pref,
                        hours_ago=self.hours_ago,
                        max_jobs=self.max_jobs_per_variant,
                    )
                    v_stat["found"] = len(raw_jobs)
                    total_found += len(raw_jobs)
                except (LinkedInRateLimitError, LinkedInBlockedError) as block_err:
                    msg = f"LinkedIn Circuit Breaker: {block_err}"
                    errors.append(msg)
                    logger.warning(msg)
                    v_stat["status"] = "BLOQUEO"
                    stats.append(v_stat)
                    break
                except Exception as e:
                    err_msg = f"Error scrapeando '{q_text}' en LinkedIn: {e}"
                    errors.append(err_msg)
                    logger.error(err_msg)
                    v_stat["status"] = "ERROR"
                    stats.append(v_stat)
                    continue

                inserted_this = 0
                duplicates_this = 0

                try:
                    with engine.begin() as conn:
                        for job in raw_jobs:
                            try:
                                with conn.begin_nested():
                                    _, _, was_inserted = process_and_store_job(
                                        conn=conn,
                                        job=job,
                                        profile=profile,
                                        cutoff=None,
                                        errors=errors,
                                        variant_id=v_id,
                                        allowed_sources=["linkedin"],
                                        verbose=False,
                                    )
                                if was_inserted:
                                    inserted_this += 1
                                    total_inserted += 1
                                else:
                                    duplicates_this += 1
                                    total_duplicates += 1
                            except Exception as job_err:
                                errors.append(f"Error guardando job {job.get('external_id')}: {job_err}")
                except Exception as db_err:
                    err_msg = f"Error transaccional en DB al procesar variante '{q_text}': {db_err}"
                    errors.append(err_msg)
                    logger.error(err_msg)
                    v_stat["status"] = "DB_ERROR"

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
