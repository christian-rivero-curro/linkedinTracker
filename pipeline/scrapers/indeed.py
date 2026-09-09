"""
Implementación base para Indeed (global / multirregión).
Preparada para conectar mediante scraping con proxies o API de Publisher.
"""
import logging
from typing import Any

from pipeline.scrapers.base import BaseJobScraper

logger = logging.getLogger("scrapers.indeed")


class IndeedScraper(BaseJobScraper):
    source_id = "indeed"
    source_name = "Indeed"
    description = "Metabuscador global de empleo con gran cobertura de ofertas directas y de agencias."
    is_available = False
    badge_status = "coming_soon"
    badge_label = "Próximamente"
    icon = "🟣"

    def scrape_user(
        self,
        engine,
        user_id: int,
        profile: dict,
        variants: list[dict],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Punto de entrada cuando se active Indeed.
        Normaliza cada vacante al formato canónico:
        {
            "external_id": f"indeed_{job_jk}",
            "title": ...,
            "company": ...,
            "location": ...,
            "remote_type": ...,
            "description": ...,
            "apply_link": ...,
            "source": "indeed",
            "posted_at": ...,
        }
        """
        if not self.is_available:
            return {
                "source": self.source_id,
                "found": 0,
                "inserted": 0,
                "duplicates": 0,
                "errors": [
                    "El conector de Indeed está en desarrollo (Próximamente)."
                ],
                "stats_per_variant": [],
            }

        return {
            "source": self.source_id,
            "found": 0,
            "inserted": 0,
            "duplicates": 0,
            "errors": [],
            "stats_per_variant": [],
        }
