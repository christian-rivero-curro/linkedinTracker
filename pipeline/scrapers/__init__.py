"""
Módulo de scrapers y fuentes de vacantes.
"""
from pipeline.scrapers.base import BaseJobScraper
from pipeline.scrapers.registry import (
    get_all_sources_metadata,
    get_available_sources,
    get_scraper,
    register_scraper,
)

__all__ = [
    "BaseJobScraper",
    "get_all_sources_metadata",
    "get_available_sources",
    "get_scraper",
    "register_scraper",
]
