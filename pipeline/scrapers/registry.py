"""
Registro central de fuentes y scrapers de vacantes.
Permite descubrir qué plataformas están disponibles, obtener sus instancias
y consultar metadatos para renderizar en la interfaz gráfica.
"""
from typing import Any
from pipeline.scrapers.base import BaseJobScraper
from pipeline.scrapers.linkedin import LinkedInScraper
from pipeline.scrapers.topsalaries import TopSalariesScraper
from pipeline.scrapers.infojobs import InfoJobsScraper
from pipeline.scrapers.indeed import IndeedScraper

_SCRAPERS: dict[str, BaseJobScraper] = {
    "linkedin": LinkedInScraper(),
    "topsalaries": TopSalariesScraper(),
    "infojobs": InfoJobsScraper(),
    "indeed": IndeedScraper(),
}


def get_all_sources_metadata() -> list[dict[str, Any]]:
    """Devuelve la lista de metadatos de todas las fuentes registradas para el frontend."""
    return [scraper.get_metadata() for scraper in _SCRAPERS.values()]


def get_available_sources() -> list[str]:
    """Devuelve los IDs de fuentes que están actualmente implementadas y listas para usar."""
    return [s_id for s_id, s in _SCRAPERS.items() if s.is_available]


def get_scraper(source_id: str) -> BaseJobScraper | None:
    """Obtiene el scraper correspondiente a un ID o None si no existe."""
    return _SCRAPERS.get(source_id.lower().strip())


def register_scraper(scraper: BaseJobScraper) -> None:
    """Permite registrar dinámicamente un nuevo scraper en tiempo de ejecución."""
    _SCRAPERS[scraper.source_id] = scraper
