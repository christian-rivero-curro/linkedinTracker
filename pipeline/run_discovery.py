"""
Entrypoint CLI / GitHub Actions para el descubrimiento multi-fuente de vacantes.
Ejecuta de forma unificada los scrapers activos (LinkedIn, TopSalaries, etc.)
respetando las preferencias de cada usuario y reportando estadísticas completas.
"""
import logging
import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_engine
from pipeline.job_discovery import run_discovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_discovery")


def main() -> dict:
    started_at = datetime.now(timezone.utc)
    target_user_id = None
    raw_uid = os.environ.get("TARGET_USER_ID")
    if raw_uid and str(raw_uid).strip().isdigit():
        target_user_id = int(str(raw_uid).strip())

    sources = os.environ.get("DISCOVERY_SOURCES", "all")

    logger.info("=" * 65)
    logger.info("INICIANDO DESCUBRIMIENTO DE VACANTES MULTI-FUENTE")
    logger.info(f"Target User ID: {target_user_id or 'Todos los usuarios activos'}")
    logger.info(f"Fuentes a ejecutar: {sources}")
    logger.info("=" * 65)

    engine = get_engine()
    results = run_discovery(
        engine=engine,
        target_user_id=target_user_id,
        sources=sources,
        progress_callback=lambda msg: logger.info(f"  [progreso] {msg}"),
    )

    logger.info("=" * 65)
    logger.info("RESUMEN DE EJECUCIÓN")
    logger.info(f"Nuevas vacantes insertadas: {results.get('new_jobs_found', 0)}")
    logger.info(f"Total vacantes encontradas: {results.get('total_found', 0)}")
    logger.info(f"Duplicadas/descartadas:     {results.get('total_duplicates', 0)}")

    sources_summary = results.get("sources_summary", {})
    for s_id, s_info in sources_summary.items():
        name = s_info.get("source_name", s_id)
        ins = s_info.get("inserted", 0)
        found = s_info.get("found", 0)
        st = s_info.get("status", "UNKNOWN")
        logger.info(f"  * {name}: {ins} insertadas de {found} encontradas [{st}]")

    errors = results.get("errors", [])
    if errors:
        logger.warning(f"Errores encontrados ({len(errors)}):")
        for err in errors[:5]:
            logger.warning(f"  - {err}")

    logger.info("=" * 65)
    return results


if __name__ == "__main__":
    main()
