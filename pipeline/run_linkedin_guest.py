"""
Entrypoint del scraper de LinkedIn Guest API.
Diseñado para ejecutarse en GitHub Actions (cron cada 4h) o en local,
de forma 100% desatendida, con coste 0 € y sin riesgo de baneo de cuentas de usuario.

Buenas prácticas aplicadas:
- Resiliencia ante desconexiones de base de datos y timeouts transitorios.
- Aislamiento transaccional por oferta (SAVEPOINT) para evitar fallos en cascada.
- Respeto del Circuit Breaker de LinkedIn (detiene la ejecución limpiamente si hay bloqueo/429 persistente).
- Registro detallado de ofertas encontradas, insertadas y duplicadas por cada variante de búsqueda.
- Tabla resumen de ejecución en consola y persistencia en run_log.
"""
import logging
import os
import random
import sys
import time
import traceback
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_engine  # noqa: E402
from pipeline.embeddings import parse_pgvector  # noqa: E402
from pipeline.job_ingest import process_and_store_job  # noqa: E402
from pipeline.linkedin_guest_client import (  # noqa: E402
    LinkedInGuestClient,
    LinkedInRateLimitError,
    LinkedInBlockedError,
)
from pipeline.query_variants import get_all_variants  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_linkedin_guest")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning(f"Valor inválido para {name}='{raw}', usando default {default}.")
        return default


LINKEDIN_HOURS_AGO = max(1, _int_env("LINKEDIN_HOURS_AGO", 4))
LINKEDIN_MAX_JOBS_PER_VARIANT = max(1, _int_env("LINKEDIN_MAX_JOBS_PER_VARIANT", 25))


def load_active_users(engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, username FROM app_user WHERE is_active = TRUE ORDER BY id ASC")
        ).mappings().all()
    return [dict(r) for r in rows]


def load_profile_by_user(engine, user_id: int, max_retries: int = 3) -> dict | None:
    """Carga el perfil de un usuario con reintentos defensivos ante desconexiones de Postgres."""
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT * FROM profile WHERE user_id = :uid"),
                    {"uid": user_id},
                ).mappings().first()
            if row is None:
                return None
            profile = dict(row)
            profile["embedding"] = parse_pgvector(profile["embedding"])
            return profile
        except (OperationalError, DBAPIError) as e:
            wait_s = (attempt + 1) * 2.0
            logger.warning(f"Fallo de conexión a BD cargando perfil user_id={user_id} ({e}). Reintentando en {wait_s}s...")
            time.sleep(wait_s)
        except Exception as e:
            logger.error(f"Error inesperado cargando perfil user_id={user_id}: {e}")
            return None
    return None


def _format_summary_table(stats_list: list[dict], total_duration_s: float) -> str:
    """Genera una tabla visual limpia con las métricas por variante."""
    header = (
        "\n"
        + "=" * 82 + "\n"
        + "RESUMEN DE EJECUCIÓN POR VARIANTE (LINKEDIN GUEST SCRAPER)\n"
        + "=" * 82 + "\n"
        + f"{'ID':<4} | {'Variante':<28} | {'Encontradas':<11} | {'Nuevas':<7} | {'Duplicadas':<10} | {'Estado':<8}\n"
        + "-" * 82
    )
    rows = []
    tot_found = 0
    tot_new = 0
    tot_dup = 0

    for s in stats_list:
        v_id = str(s.get("id", "-"))
        v_query = (s.get("query") or "")[:28]
        found = s.get("found", 0)
        new_cnt = s.get("inserted", 0)
        dup_cnt = s.get("duplicates", 0)
        status = s.get("status", "OK")

        tot_found += found
        tot_new += new_cnt
        tot_dup += dup_cnt

        rows.append(
            f"{v_id:<4} | {v_query:<28} | {found:<11} | {new_cnt:<7} | {dup_cnt:<10} | {status:<8}"
        )

    footer = (
        "-" * 82 + "\n"
        + f"{'TOTAL':<4} | {f'{len(stats_list)} variantes':<28} | {tot_found:<11} | {tot_new:<7} | {tot_dup:<10} | "
        + f"{tot_new} insertadas\n"
        + f"Duración total: {total_duration_s:.1f}s | Ventana temporal: últimas {LINKEDIN_HOURS_AGO}h\n"
        + "=" * 82 + "\n"
    )
    return header + "\n" + "\n".join(rows) + "\n" + footer


def _log_run_safe(engine, started_at: datetime, new_jobs_found: int, errors: list[str], summary_text: str | None = None):
    """Registra la corrida en run_log de forma segura con reintento."""
    if engine is None:
        return

    log_content = []
    if summary_text:
        log_content.append(summary_text.strip())
    if errors:
        log_content.append("ERRORES:\n" + "\n".join(errors))

    payload = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc),
        "new_jobs_found": new_jobs_found,
        "errors": "\n\n".join(log_content) if log_content else None,
    }

    for attempt in range(2):
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO run_log (started_at, finished_at, jsearch_calls_used, llm_calls_used, new_jobs_found, errors)
                        VALUES (:started_at, :finished_at, 0, 0, :new_jobs_found, :errors)
                    """),
                    payload,
                )
            break
        except Exception as e:
            if attempt == 0:
                time.sleep(2.0)
            else:
                logger.error(f"No se pudo registrar la ejecución en run_log tras reintento: {e}")


def main():
    started_at = datetime.now(timezone.utc)
    new_jobs_found = 0
    errors = []
    engine = None
    variant_stats = []

    try:
        engine = get_engine()
        active_users = load_active_users(engine)
        if not active_users:
            msg = "No hay usuarios activos registrados en app_user. Regístrate en el portal primero."
            logger.warning(msg)
            return

        logger.info(f"Usuarios activos a procesar: {len(active_users)} {[u['username'] for u in active_users]}")
        circuit_broken = False

        with LinkedInGuestClient() as client:
            for user in active_users:
                if circuit_broken:
                    break

                user_id = user["id"]
                username = user["username"]
                logger.info(f"\n{'#'*60}\nPROCESANDO USUARIO: '{username}' (id={user_id})\n{'#'*60}")

                profile = load_profile_by_user(engine, user_id=user_id)
                if profile is None:
                    logger.warning(f"Usuario '{username}' no tiene perfil/CV configurado. Saltando.")
                    continue

                location = profile.get("location_preference")
                remote_pref = profile.get("remote_preference")
                logger.info(f"Perfil cargado ({username}): location={location!r}, remote={remote_pref!r}")

                try:
                    variants = [v for v in get_all_variants(engine, user_id=user_id) if v.get("is_active", True)]
                except Exception as ve:
                    msg = f"Error obteniendo variantes para {username}: {ve}"
                    errors.append(msg)
                    logger.error(msg)
                    continue

                if not variants:
                    logger.warning(f"Usuario '{username}' no tiene variantes activas. Saltando.")
                    continue

                logger.info(f"Procesando {len(variants)} variante(s) para {username}:")
                for idx, variant in enumerate(variants, 1):
                    if circuit_broken:
                        break

                    query_text = variant["query_text"]
                    variant_id = variant["id"]
                    logger.info(f"\n{'='*20} [{idx}/{len(variants)}] ({username}) '{query_text}' (id={variant_id}) {'='*20}")

                    v_stat = {
                        "id": variant_id,
                        "query": f"{username}: {query_text}",
                        "found": 0,
                        "inserted": 0,
                        "duplicates": 0,
                        "status": "OK",
                    }

                    try:
                        raw_jobs = client.scrape_variant(
                            query_text=query_text,
                            location=location,
                            remote_preference=remote_pref,
                            hours_ago=LINKEDIN_HOURS_AGO,
                            max_jobs=LINKEDIN_MAX_JOBS_PER_VARIANT,
                        )
                        v_stat["found"] = len(raw_jobs)
                        logger.info(f"Variante '{query_text}': {len(raw_jobs)} ofertas encontradas en LinkedIn.")
                    except (LinkedInRateLimitError, LinkedInBlockedError) as block_err:
                        msg = f"DETENCIÓN DE SEGURIDAD: {block_err}. Abortando siguientes variantes."
                        errors.append(msg)
                        logger.error(msg)
                        v_stat["status"] = "BLOQUEO"
                        variant_stats.append(v_stat)
                        circuit_broken = True
                        break
                    except Exception as e:
                        err_msg = f"Error scrapeando variante '{query_text}' de {username}: {e}"
                        errors.append(err_msg)
                        logger.error(err_msg)
                        v_stat["status"] = "ERROR"
                        variant_stats.append(v_stat)
                        continue

                inserted_this_variant = 0
                duplicates_this_variant = 0

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
                                        variant_id=variant_id,
                                        allowed_sources=["linkedin"],
                                        verbose=False,
                                    )
                                if was_inserted:
                                    new_jobs_found += 1
                                    inserted_this_variant += 1
                                    logger.info(f"  [+] INSERTADA: '{job.get('title')}' - {job.get('company')} ({job.get('external_id')})")
                                else:
                                    duplicates_this_variant += 1
                                    logger.info(f"  [-] DESCARTADA/DUPLICADA: '{job.get('title')}' - {job.get('company')} ({job.get('external_id')})")
                            except Exception as job_err:
                                err_msg = f"Error guardando job {job.get('external_id')}: {job_err}"
                                errors.append(err_msg)
                                logger.error(err_msg)

                except Exception as db_err:
                    err_msg = f"Error en transacción de BD para variante '{query_text}': {db_err}"
                    errors.append(err_msg)
                    logger.error(err_msg)
                    v_stat["status"] = "ERROR_BD"

                v_stat["inserted"] = inserted_this_variant
                v_stat["duplicates"] = duplicates_this_variant
                variant_stats.append(v_stat)

                logger.info(
                    f"-> Resumen variante '{query_text}': {v_stat['found']} encontradas | "
                    f"{v_stat['inserted']} nuevas insertadas | {v_stat['duplicates']} duplicadas/descartadas."
                )
                time.sleep(random.uniform(2.5, 5.0))

    except Exception:
        exc_str = traceback.format_exc()
        errors.append(exc_str)
        logger.error(f"Fallo crítico inesperado: {exc_str}")
    finally:
        total_duration_s = (datetime.now(timezone.utc) - started_at).total_seconds()
        summary_table = _format_summary_table(variant_stats, total_duration_s)
        # Imprimir tabla resumen clara en los logs de consola
        print(summary_table)

        if errors:
            logger.warning(f"Incidencias durante la corrida ({len(errors)}):")
            for err in errors[:5]:
                logger.warning(f"  * {err}")

        _log_run_safe(engine, started_at, new_jobs_found, errors, summary_text=summary_table)


if __name__ == "__main__":
    main()
