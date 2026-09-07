"""
Entrypoint del cron (GitHub Actions, cada 4h).
Orquesta todo el pipeline de descubrimiento y scoring de ofertas.

Cada ejecucion consulta TODAS las variantes de busqueda activas (no una sola
por rotacion), y por cada variante pagina hasta JSEARCH_MAX_PAGES_PER_VARIANT
paginas o hasta que los resultados dejen de aportar ofertas mas recientes que
el cutoff de esa variante - lo que ocurra antes. Esto es deliberadamente mas
costoso en cuota de JSearch que una unica llamada por ejecucion, a cambio de
un barrido mas exhaustivo del perfil. Hay un corte de seguridad por
presupuesto mensual que impide superar JSEARCH_MONTHLY_BUDGET.

El cutoff por variante es un filtro RELATIVO (anti-solapamiento entre
ejecuciones sucesivas de la misma variante): en la primera ejecucion de una
variante (cutoff=None) no descarta nada por fecha. Como JSearch agrega
fuentes de terceros con metadata de fecha poco fiable (date_posted='month' no
es una garantia dura), se aplica ademas JSEARCH_MAX_JOB_AGE_DAYS como techo
ABSOLUTO de antiguedad, independiente del cutoff.

Fail-soft: nunca debe terminar con excepcion no controlada, incluida la
lectura de configuracion (variables de entorno mal escritas usan su default
en vez de tumbar el modulo entero al importarlo).
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
from pipeline.embeddings import embed_text, cosine_similarity, to_pgvector_literal, parse_pgvector  # noqa: E402
from pipeline.scoring import (  # noqa: E402
    is_blacklisted,
    hard_requirements_score,
    evaluate_job_with_llm,
    compute_final_score,
)
from pipeline.query_variants import get_or_seed_variants, mark_variant_run  # noqa: E402


def _int_env(name: str, default: int) -> int:
    """
    Lee una variable de entorno como int de forma segura. Si falta, esta vacia
    o no es convertible, devuelve el default sin lanzar excepcion - un typo en
    la configuracion (ej. JSEARCH_MAX_PAGES_PER_VARIANT='3,') no debe tumbar
    todo el cron a nivel de import, antes incluso de llegar a main().
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        print(f"[run_discovery] Valor invalido para {name}='{raw}', usando default {default}.")
        return default


JSEARCH_MONTHLY_BUDGET = _int_env("JSEARCH_MONTHLY_BUDGET", 180)
LLM_DAILY_BUDGET = _int_env("LLM_DAILY_BUDGET", 48)
TOP_N_FOR_LLM = 8
VECTOR_SIMILARITY_THRESHOLD = 0.55
MAX_PAGES_PER_VARIANT = max(1, _int_env("JSEARCH_MAX_PAGES_PER_VARIANT", 3))
JSEARCH_PAGE_SIZE_HINT = 10  # heuristica: una pagina con menos resultados que esto se asume la ultima
MAX_JOB_AGE_DAYS = max(1, _int_env("JSEARCH_MAX_JOB_AGE_DAYS", 35))


def check_budget(engine) -> tuple[bool, int, int]:
    with engine.connect() as conn:
        since_month = datetime.now(timezone.utc) - timedelta(days=30)
        jsearch_used = conn.execute(
            text("SELECT COALESCE(SUM(jsearch_calls_used),0) FROM run_log WHERE started_at >= :since"),
            {"since": since_month},
        ).scalar()
        since_day = datetime.now(timezone.utc) - timedelta(days=1)
        llm_used = conn.execute(
            text("SELECT COALESCE(SUM(llm_calls_used),0) FROM run_log WHERE started_at >= :since"),
            {"since": since_day},
        ).scalar()
    can_run = jsearch_used < JSEARCH_MONTHLY_BUDGET
    return can_run, jsearch_used, llm_used


def load_profile(engine) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM profile WHERE id = 1")).mappings().first()
    if row is None:
        return None
    profile = dict(row)
    profile["embedding"] = parse_pgvector(profile["embedding"])
    return profile


def safe_text(value) -> str:
    """Fuerza cualquier valor a str no vacio, para evitar tipos inesperados en embed_text()."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    return value


def parse_posted_at(value):
    """Parseo defensivo del timestamp de publicacion de una oferta. Nunca lanza:
    si no se puede interpretar, devuelve None (y esa oferta no se filtra por cutoff,
    se procesa igualmente para no perder posibles matches por un formato inesperado).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text_value = str(value).strip()
        if text_value.endswith("Z"):
            text_value = text_value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text_value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _process_job(conn, raw, profile, cutoff, errors) -> tuple[bool, object, bool]:
    """
    Procesa una oferta cruda de JSearch dentro de la transaccion `conn`.
    Devuelve (es_fresca, posted_at, fue_insertada):
      - es_fresca: si cae dentro de la ventana temporal de la variante (para
        decidir si seguir paginando).
      - posted_at: timestamp parseado (o None), para actualizar el cutoff.
      - fue_insertada: True solo si se inserto una fila nueva en job_offer.
    No lanza excepciones de negocio: los fallos puntuales (embedding, etc.)
    se registran en `errors` y la oferta se salta sin insertar.

    Aplica dos filtros de fecha distintos:
    1. Techo absoluto (MAX_JOB_AGE_DAYS): descarta ofertas demasiado viejas
       SIEMPRE, incluso en la primera ejecucion de una variante (cutoff=None).
       Necesario porque el date_posted='month' de la API no es una garantia
       dura (metadata de fecha poco fiable en fuentes agregadas).
    2. Cutoff relativo por variante: evita reprocesar lo ya visto entre
       ejecuciones sucesivas de la MISMA variante.
    """
    job = normalize_job(raw)
    if not job["external_id"] or not job["apply_link"]:
        return False, None, False

    posted_at = parse_posted_at(job.get("posted_at"))

    if posted_at is not None:
        max_age_threshold = datetime.now(timezone.utc) - timedelta(days=MAX_JOB_AGE_DAYS)
        if posted_at < max_age_threshold:
            return False, posted_at, False

    is_fresh = cutoff is None or posted_at is None or posted_at > cutoff
    if not is_fresh:
        return False, posted_at, False

    if is_blacklisted(job["title"]) and not any(
        kw in job["title"].lower() for kw in profile.get("role_family", [])
    ):
        return True, posted_at, False

    existing = conn.execute(
        text("SELECT id FROM job_offer WHERE external_id = :eid"),
        {"eid": job["external_id"]},
    ).first()
    if existing:
        return True, posted_at, False

    title_str = safe_text(job.get("title"))
    description_str = safe_text(job.get("description"))
    embed_input = f"{title_str} {description_str}".strip() or "oferta sin descripcion"

    try:
        job_embedding = embed_text(embed_input)
    except Exception as e:
        errors.append(f"Error generando embedding para job {job['external_id']}: {e}")
        return True, posted_at, False

    similarity = cosine_similarity(job_embedding, profile["embedding"])

    result = conn.execute(
        text("""
            INSERT INTO job_offer (external_id, title, company, location, remote_type,
                description, apply_link, source, salary_min, salary_max, posted_at, embedding)
            VALUES (:external_id, :title, :company, :location, :remote_type,
                :description, :apply_link, :source, :salary_min, :salary_max, :posted_at, CAST(:embedding AS vector))
            RETURNING id
        """),
        {**job, "embedding": to_pgvector_literal(job_embedding)},
    )
    job_offer_id = result.scalar()

    conn.execute(
        text("""
            INSERT INTO job_score (job_offer_id, profile_id, vector_similarity, llm_evaluated, final_score)
            VALUES (:job_offer_id, 1, :similarity, FALSE, :final_score)
            ON CONFLICT (job_offer_id, profile_id) DO NOTHING
        """),
        {"job_offer_id": job_offer_id, "similarity": similarity, "final_score": similarity * 100},
    )
    return True, posted_at, True


def main():
    engine = get_engine()
    started_at = datetime.now(timezone.utc)
    jsearch_calls = 0
    llm_calls = 0
    new_jobs_found = 0
    errors = []

    try:
        profile = load_profile(engine)
        if profile is None:
            errors.append("No hay perfil configurado (profile.id=1). Completa el onboarding primero.")
            return

        can_run, jsearch_used_month, llm_used_today = check_budget(engine)
        if not can_run:
            errors.append(f"Presupuesto JSearch agotado ({jsearch_used_month}/{JSEARCH_MONTHLY_BUDGET} este mes).")
            return

        try:
            variants = get_or_seed_variants(engine, 1, profile)
        except RuntimeError as e:
            errors.append(str(e))
            return

        remote_only = profile.get("remote_preference") == "remote"
        location = profile.get("location_preference")
        budget_exhausted = False

        for variant in variants:
            if budget_exhausted:
                errors.append(
                    f"Presupuesto JSearch agotado tras {jsearch_calls} llamadas en esta ejecucion; "
                    f"variante '{variant['query_text']}' (y las siguientes) se omiten hasta la proxima ejecucion."
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
                            is_fresh, posted_at, was_inserted = _process_job(conn, raw, profile, cutoff, errors)
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

        with engine.begin() as conn:
            pending = conn.execute(
                text("""
                    SELECT js.id AS score_id, js.job_offer_id, js.vector_similarity, jo.*
                    FROM job_score js
                    JOIN job_offer jo ON jo.id = js.job_offer_id
                    WHERE js.llm_evaluated = FALSE AND js.vector_similarity >= :threshold
                    ORDER BY js.vector_similarity DESC
                    LIMIT :limit
                """),
                {"threshold": VECTOR_SIMILARITY_THRESHOLD, "limit": TOP_N_FOR_LLM},
            ).mappings().all()

            for row in pending:
                if llm_used_today + llm_calls >= LLM_DAILY_BUDGET:
                    break
                try:
                    evaluation = evaluate_job_with_llm(profile["extracted_json"], dict(row))
                    llm_calls += 1
                except Exception as e:
                    errors.append(f"LLM error en job {row['job_offer_id']}: {e}")
                    continue

                hard_score = hard_requirements_score(profile, dict(row))
                final_score = compute_final_score(row["vector_similarity"], hard_score, evaluation["llm_score"])

                conn.execute(
                    text("""
                        UPDATE job_score SET llm_score = :llm_score, llm_evaluated = TRUE,
                            pros = :pros, cons = :cons, missing_requirements = :missing,
                            recommendation = :recommendation, final_score = :final_score
                        WHERE id = :score_id
                    """),
                    {
                        "llm_score": evaluation["llm_score"],
                        "pros": evaluation["pros"],
                        "cons": evaluation["cons"],
                        "missing": evaluation["missing_requirements"],
                        "recommendation": evaluation["recommendation"],
                        "final_score": final_score,
                        "score_id": row["score_id"],
                    },
                )

    except Exception:
        errors.append(traceback.format_exc())
    finally:
        _log_run(engine, started_at, jsearch_calls, llm_calls, new_jobs_found, errors)


def _log_run(engine, started_at, jsearch_calls, llm_calls, new_jobs_found, errors):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO run_log (started_at, finished_at, jsearch_calls_used, llm_calls_used, new_jobs_found, errors)
                VALUES (:started_at, :finished_at, :jsearch_calls, :llm_calls, :new_jobs_found, :errors)
            """),
            {
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "jsearch_calls": jsearch_calls,
                "llm_calls": llm_calls,
                "new_jobs_found": new_jobs_found,
                "errors": "\n".join(errors) if errors else None,
            },
        )
    if errors:
        print("Errores durante la ejecucion:", *errors, sep="\n")
    print(f"Ejecucion finalizada. Ofertas nuevas: {new_jobs_found}. JSearch calls: {jsearch_calls}. LLM calls: {llm_calls}.")


if __name__ == "__main__":
    main()
