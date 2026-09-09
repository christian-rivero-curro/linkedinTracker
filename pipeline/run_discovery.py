"""
Entrypoint del cron de DESCUBRIMIENTO via JSearch (GitHub Actions, cada 4h).
Solo busca ofertas en JSearch y las guarda en la base de datos con su
similitud vectorial. La logica de insercion (dedup, filtros, embedding) esta
centralizada en pipeline/job_ingest.py, compartida con pipeline/run_linkedin_scrape.py
(el scraper de LinkedIn, pensado para correr en local/Docker, no aqui).

La evaluacion cualitativa por LLM vive en un script aparte
(pipeline/run_llm_evaluation.py), que corre cada 5 minutos de forma
independiente: JSearch tiene una cuota mensual real y limitada, por lo que
ese descubrimiento debe seguir siendo espaciado; el LLM usado es un modelo
:free de OpenRouter sin limite diario real en la cuenta actual, asi que no
tiene sentido atarlo a la misma cadencia de 4h.

Cada ejecucion consulta TODAS las variantes de busqueda activas (no una sola
por rotacion), y por cada variante pagina hasta JSEARCH_MAX_PAGES_PER_VARIANT
paginas o hasta que los resultados dejen de aportar ofertas mas recientes que
el cutoff de esa variante - lo que ocurra antes. Hay un corte de seguridad por
presupuesto mensual que impide superar JSEARCH_MONTHLY_BUDGET.

El cutoff por variante es un filtro RELATIVO (anti-solapamiento entre
ejecuciones sucesivas de la misma variante): en la primera ejecucion de una
variante (cutoff=None) no descarta nada por fecha. Como JSearch agrega
fuentes de terceros con metadata de fecha poco fiable, se aplica ademas
JSEARCH_MAX_JOB_AGE_DAYS como techo ABSOLUTO de antiguedad (en job_ingest.py).

Solo se guardan ofertas cuyo publisher se clasifique como LinkedIn
(JSEARCH_SOURCE_FILTER, por defecto 'linkedin'). jsearch_client.py ya pide
"via linkedin" en la query, pero eso no es una garantia estricta de la API -
el filtro real que asegura esto es allowed_sources en job_ingest.py.

Fail-soft: nunca debe terminar con excepcion no controlada, incluida la
lectura de configuracion.
"""
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_engine  # noqa: E402
from pipeline.jsearch_client import search_jobs, normalize_job  # noqa: E402
from pipeline.embeddings import parse_pgvector, embed_text, to_pgvector_literal  # noqa: E402
from pipeline.job_ingest import process_and_store_job  # noqa: E402
from pipeline.query_variants import get_or_seed_variants, mark_variant_run  # noqa: E402


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        print(f"[run_discovery] Valor invalido para {name}='{raw}', usando default {default}.")
        return default


JSEARCH_MONTHLY_BUDGET = _int_env("JSEARCH_MONTHLY_BUDGET", 180)
MAX_PAGES_PER_VARIANT = max(1, _int_env("JSEARCH_MAX_PAGES_PER_VARIANT", 3))
JSEARCH_PAGE_SIZE_HINT = 10  # heuristica: una pagina con menos resultados que esto se asume la ultima
# Debe coincidir con JSEARCH_SOURCE_FILTER de jsearch_client.py. Vacio = sin filtro (acepta cualquier fuente).
REQUIRED_SOURCE = os.environ.get("JSEARCH_SOURCE_FILTER", "linkedin").strip().lower()


def check_budget(engine) -> tuple[bool, int]:
    with engine.connect() as conn:
        since_month = datetime.now(timezone.utc) - timedelta(days=30)
        jsearch_used = conn.execute(
            text("SELECT COALESCE(SUM(jsearch_calls_used),0) FROM run_log WHERE started_at >= :since"),
            {"since": since_month},
        ).scalar()
    can_run = jsearch_used < JSEARCH_MONTHLY_BUDGET
    return can_run, jsearch_used


def load_active_users(engine, target_user_id: int | None = None) -> list[dict]:
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
    return [dict(r) for r in rows]


def load_profile_by_user(engine, user_id: int) -> dict | None:
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
            print(f"[discovery] Generando vector de perfil para user_id={user_id}...")
            emb = embed_text(profile["raw_cv_text"])
            if emb:
                profile["embedding"] = emb
                with engine.begin() as save_conn:
                    save_conn.execute(
                        text("UPDATE profile SET embedding = CAST(:emb AS vector) WHERE user_id = :uid"),
                        {"emb": to_pgvector_literal(emb), "uid": user_id},
                    )
                print(f"[discovery] Vector generado y guardado para user_id={user_id}.")
        except Exception as e:
            print(f"[discovery] Error autogenerando embedding para user_id={user_id}: {e}")
    return profile


def _process_job(conn, raw, profile, cutoff, errors, variant_id) -> tuple[bool, object, bool]:
    job = normalize_job(raw)
    allowed_sources = [REQUIRED_SOURCE] if REQUIRED_SOURCE else None
    return process_and_store_job(conn, job, profile, cutoff, errors, variant_id, allowed_sources=allowed_sources)


def main(target_user_id: int | None = None):
    engine = get_engine()
    started_at = datetime.now(timezone.utc)
    jsearch_calls = 0
    new_jobs_found = 0
    errors = []

    if target_user_id is None:
        raw_uid = os.environ.get("TARGET_USER_ID")
        if raw_uid and str(raw_uid).strip().isdigit():
            target_user_id = int(str(raw_uid).strip())

    try:
        active_users = load_active_users(engine, target_user_id=target_user_id)
        if not active_users:
            print(f"No hay usuarios activos registrados{' para ID ' + str(target_user_id) if target_user_id else ''} en app_user.")
            return

        can_run, jsearch_used_month = check_budget(engine)
        if not can_run:
            errors.append(f"Presupuesto JSearch agotado ({jsearch_used_month}/{JSEARCH_MONTHLY_BUDGET} este mes).")
            return

        budget_exhausted = False

        for user in active_users:
            if budget_exhausted:
                break

            user_id = user["id"]
            username = user["username"]
            profile = load_profile_by_user(engine, user_id=user_id)
            if profile is None:
                continue

            try:
                variants = get_or_seed_variants(engine, profile["id"], profile)
            except RuntimeError as e:
                errors.append(f"User {username}: {e}")
                continue

            remote_only = profile.get("remote_preference") == "remote"
            location = profile.get("location_preference")

            for variant in variants:
                if budget_exhausted:
                    errors.append(
                        f"Presupuesto JSearch agotado tras {jsearch_calls} llamadas; omitiendo variantes restantes."
                    )
                    break


            cutoff = variant.get("last_posted_cutoff_utc")
            variant_newest_posted_at = None

            try:
                page = 1
                while page <= MAX_PAGES_PER_VARIANT:
                    if jsearch_used_month + jsearch_calls >= JSEARCH_MONTHLY_BUDGET:
                        budget_exhausted = True
                        errors.append(
                            f"Presupuesto JSearch agotado tras {jsearch_calls} llamadas en esta ejecucion; "
                            f"variante '{variant['query_text']}' pagina {page} no se llego a pedir."
                        )
                        break

                    print(
                        f"JSearch query (variante '{variant['query_text']}', id={variant['id']}, pagina {page}): "
                        f"location='{location}', remote_only={remote_only}, cutoff={cutoff}"
                    )
                    try:
                        raw_jobs = search_jobs(
                            query=variant["query_text"], location=location, remote_only=remote_only, page=page
                        )
                    except Exception as e:
                        errors.append(f"Error JSearch en variante '{variant['query_text']}' pagina {page}: {e}")
                        break
                    jsearch_calls += 1

                    if not raw_jobs:
                        break

                    page_has_fresh_job = False
                    with engine.begin() as conn:
                        for raw in raw_jobs:
                            is_fresh, posted_at, was_inserted = _process_job(
                                conn, raw, profile, cutoff, errors, variant["id"]
                            )
                            if posted_at is not None and (
                                variant_newest_posted_at is None or posted_at > variant_newest_posted_at
                            ):
                                variant_newest_posted_at = posted_at
                            if is_fresh:
                                page_has_fresh_job = True
                            if was_inserted:
                                new_jobs_found += 1

                    if cutoff is not None and not page_has_fresh_job:
                        break
                    if len(raw_jobs) < JSEARCH_PAGE_SIZE_HINT:
                        break
                    page += 1
            except Exception as e:
                errors.append(f"Error procesando variante '{variant['query_text']}': {e}")
            finally:
                try:
                    mark_variant_run(engine, variant["id"], variant_newest_posted_at)
                except Exception as e:
                    errors.append(f"Error actualizando cutoff de variante {variant.get('id')}: {e}")

    except Exception:
        errors.append(traceback.format_exc())
    finally:
        _log_run(engine, started_at, jsearch_calls, new_jobs_found, errors)


def _log_run(engine, started_at, jsearch_calls, new_jobs_found, errors):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO run_log (started_at, finished_at, jsearch_calls_used, llm_calls_used, new_jobs_found, errors)
                VALUES (:started_at, :finished_at, :jsearch_calls, 0, :new_jobs_found, :errors)
            """),
            {
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "jsearch_calls": jsearch_calls,
                "new_jobs_found": new_jobs_found,
                "errors": "\n".join(errors) if errors else None,
            },
        )
    if errors:
        print("Errores durante la ejecucion:", *errors, sep="\n")
    print(f"Ejecucion finalizada. Ofertas nuevas: {new_jobs_found}. JSearch calls: {jsearch_calls}.")


if __name__ == "__main__":
    main()
