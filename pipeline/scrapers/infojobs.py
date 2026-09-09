"""
Implementación base para el portal InfoJobs (España / Italia).
Preparada para conectar mediante la API pública de InfoJobs (OAuth2 / Client Secret)
o mediante extracción web de ofertas.
"""
import logging
from typing import Any

from pipeline.scrapers.base import BaseJobScraper
from pipeline.job_ingest import process_and_store_job

logger = logging.getLogger("scrapers.infojobs")


class InfoJobsScraper(BaseJobScraper):
    source_id = "infojobs"
    source_name = "InfoJobs"
    description = "Portal líder de empleo en España e Italia. Requiere API Key o conector de búsqueda."
    is_available = False  # Cambiar a True cuando se configure API o scraper
    badge_status = "coming_soon"
    badge_label = "Próximamente"
    icon = "🟧"

    def __init__(self, api_key: str | None = None, api_secret: str | None = None):
        self.api_key = api_key
        self.api_secret = api_secret

    def scrape_user(
        self,
        engine,
        user_id: int,
        profile: dict,
        variants: list[dict],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Punto de entrada cuando se habilite InfoJobs.
        Convierte cada oferta devuelta por InfoJobs al formato canónico de job_ingest:
        {
            "external_id": f"infojobs_{offer_id}",
            "title": offer["title"],
            "company": offer.get("author", {}).get("name"),
            "location": offer.get("city"),
            "remote_type": "remote" | "hybrid" | "onsite",
            "description": offer.get("requirementMinimum", "") + "\n" + offer.get("description", ""),
            "apply_link": offer.get("link"),
            "source": "infojobs",
            "salary_min": ...,
            "salary_max": ...,
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
                    "El conector de InfoJobs está en desarrollo (Próximamente)."
                ],
                "stats_per_variant": [],
            }

        # Ejemplo de flujo cuando esté implementado:
        # 1. Autenticar o construir cliente HTTP InfoJobs
        # 2. Iterar por variantes activas
        # 3. Mapear y procesar con process_and_store_job(conn, job, profile, ...)
        return {
            "source": self.source_id,
            "found": 0,
            "inserted": 0,
            "duplicates": 0,
            "errors": [],
            "stats_per_variant": [],
        }
