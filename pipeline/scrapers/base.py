"""
Clase base y contrato formal para todos los scrapers de vacantes.
Permite añadir fácilmente nuevas plataformas (LinkedIn, InfoJobs, Indeed, Tecnoempleo, etc.)
garantizando normalización de datos y manejo resiliente de errores.
"""
from abc import ABC, abstractmethod
from typing import Any


class BaseJobScraper(ABC):
    source_id: str = "unknown"
    source_name: str = "Desconocido"
    description: str = ""
    is_available: bool = False
    badge_status: str = "coming_soon"  # "active" | "coming_soon" | "beta"
    badge_label: str = "Próximamente"
    icon: str = "💼"

    def get_metadata(self) -> dict[str, Any]:
        """Devuelve los metadatos públicos de la fuente para el frontal."""
        return {
            "id": self.source_id,
            "name": self.source_name,
            "description": self.description,
            "is_available": self.is_available,
            "badge_status": self.badge_status,
            "badge_label": self.badge_label,
            "icon": self.icon,
        }

    @abstractmethod
    def scrape_user(
        self,
        engine,
        user_id: int,
        profile: dict,
        variants: list[dict],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Ejecuta la búsqueda y guardado de ofertas para un usuario concreto y sus variantes.
        
        Debe devolver un diccionario con:
        {
            "source": self.source_id,
            "found": int,
            "inserted": int,
            "duplicates": int,
            "errors": list[str],
            "stats_per_variant": list[dict],
        }
        """
        pass
