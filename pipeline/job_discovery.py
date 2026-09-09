"""
Orquestador unificado y modular de búsqueda y descubrimiento de vacantes.
Ejecuta los scrapers solicitados de forma aislada, reporta el progreso
y consolida los resultados para la base de datos y la interfaz web.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import text

from pipeline.embeddings import parse_pgvector, embed_text, to_pgvector_literal
from pipeline.query_variants import get_all_variants
from pipeline.scrapers.registry import (
    get_available_sources,
    get_scraper,
    get_all_sources_metadata,
)

logger = logging.getLogger("job_discovery")


def load_profile_by_user(engine, user_id: int) -> dict | None:
    """Carga el perfil de un usuario y asegura que su embedding esté calculado."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM profile WHERE user_id = :uid"),
            {"uid": user_id},
        ).mappings().first()
    if row is None:
        return None
    profile = dict(row)
    profile["embedding"] = parse_pgvector(profile.get("embedding"))
    emb_list = profile["embedding"]
    needs_embedding = (not emb_list) or all(v == 0.0 for v in emb_list)
    if needs_embedding and profile.get("raw_cv_text"):
        try:
            emb = embed_text(profile["raw_cv_text"])
            if emb:
                profile["embedding"] = emb
                with engine.begin() as save_conn:
                    save_conn.execute(
                        text("UPDATE profile SET embedding = CAST(:emb AS vector) WHERE user_id = :uid"),
                        {"emb": to_pgvector_literal(emb), "uid": user_id},
                    )
        except Exception as e:
            logger.warning(f"No se pudo generar embedding para user_id={user_id}: {e}")
    return profile


def run_discovery(
    engine,
    target_user_id: int | None = None,
    sources: list[str] | str = "all",
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Ejecuta el ciclo de descubrimiento de ofertas para el usuario o usuarios indicados,
    restringido a las fuentes especificadas.
    """
    started_at = datetime.now(timezone.utc)
    total_found = 0
    total_inserted = 0
    total_duplicates = 0
    all_errors: list[str] = []
    sources_summary: dict[str, dict] = {}

    # 1. Obtener usuarios activos
    with engine.connect() as conn:
        if target_user_id is not None:
            rows = conn.execute(
                text("SELECT id, username FROM app_user WHERE is_active = TRUE AND id = :uid ORDER BY id ASC"),
                {"uid": target_user_id},
            ).mappings().all()
        else:
            rows = conn.execute(
                text("SELECT id, username FROM app_user WHERE is_active = TRUE ORDER BY id ASC")
            ).mappings().all()
    active_users = [dict(r) for r in rows]

    if not active_users:
        msg = f"No hay usuarios activos registrados{' para ID ' + str(target_user_id) if target_user_id else ''}."
        logger.warning(msg)
        return {
            "new_jobs_found": 0,
            "total_found": 0,
            "errors": [msg],
            "sources_summary": {},
        }

    for user in active_users:
        user_id = user["id"]
        username = user["username"]

        profile = load_profile_by_user(engine, user_id=user_id)
        if profile is None:
            logger.warning(f"Usuario '{username}' no tiene perfil/CV configurado. Saltando.")
            continue

        try:
            variants = [v for v in get_all_variants(engine, user_id=user_id) if v.get("is_active", True)]
        except Exception as ve:
            err = f"Error obteniendo variantes de búsqueda para {username}: {ve}"
            all_errors.append(err)
            logger.error(err)
            continue

        if not variants:
            logger.warning(f"Usuario '{username}' no tiene variantes activas. Saltando.")
            continue

        # Determinar fuentes a ejecutar para este usuario
        configured_sources = profile.get("enabled_sources") or ["linkedin"]
        
        target_sources: list[str] = []
        if isinstance(sources, str):
            if sources.lower() == "all":
                target_sources = list(configured_sources)
            else:
                target_sources = [s.strip().lower() for s in sources.split(",") if s.strip()]
        elif isinstance(sources, list):
            target_sources = [s.strip().lower() for s in sources if s.strip()]
        else:
            target_sources = list(configured_sources)

        if not target_sources:
            target_sources = ["linkedin"]

        logger.info(f"Usuario '{username}' (id={user_id}): ejecutando fuentes {target_sources}")

        for s_id in target_sources:
            scraper = get_scraper(s_id)
            if not scraper:
                msg = f"Fuente '{s_id}' no reconocida en el registro de scrapers."
                all_errors.append(msg)
                logger.warning(msg)
                continue

            if not scraper.is_available:
                msg = f"La fuente '{scraper.source_name}' aún no está activa ({scraper.badge_label})."
                all_errors.append(msg)
                logger.info(msg)
                sources_summary[s_id] = {
                    "source_name": scraper.source_name,
                    "found": 0,
                    "inserted": 0,
                    "duplicates": 0,
                    "status": scraper.badge_status,
                    "message": msg,
                }
                continue

            if progress_callback:
                progress_callback(f"Buscando ofertas en {scraper.source_name}...")

            logger.info(f"Iniciando scraper '{scraper.source_name}' para {username}...")
            res = scraper.scrape_user(
                engine=engine,
                user_id=user_id,
                profile=profile,
                variants=variants,
            )

            found = res.get("found", 0)
            inserted = res.get("inserted", 0)
            duplicates = res.get("duplicates", 0)
            errors = res.get("errors", [])

            total_found += found
            total_inserted += inserted
            total_duplicates += duplicates
            all_errors.extend(errors)

            sources_summary[s_id] = {
                "source_name": scraper.source_name,
                "found": found,
                "inserted": inserted,
                "duplicates": duplicates,
                "errors": errors,
                "status": "OK" if not errors else "PARTIAL_ERROR",
            }

    return {
        "new_jobs_found": total_inserted,
        "total_found": total_found,
        "total_duplicates": total_duplicates,
        "errors": all_errors,
        "sources_summary": sources_summary,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
