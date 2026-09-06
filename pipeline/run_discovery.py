"""
Entrypoint del cron (GitHub Actions, cada 4h).
Orquesta todo el pipeline de descubrimiento y scoring de ofertas.
Fail-soft: nunca debe terminar con excepcion no controlada.
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
from pipeline.query_variants import get_or_seed_variant, mark_variant_run  # noqa: E402

JSEARCH_MONTHLY_BUDGET = int(os.environ.get("JSEARCH_MONTHLY_BUDGET", 180))
LLM_DAILY_BUDGET = int(os.environ.get("LLM_DAILY_BUDGET", 48))
TOP_N_FOR_LLM = 8
VECTOR_SIMILARITY_THRESHOLD = 0.55


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


def main():
    engine = get_engine()
    started_at = datetime.now(timezone.utc)
    jsearch_calls = 0
    llm_calls = 0
    new_jobs_found = 0
    errors = []
    variant = None
    newest_posted_at = None

    try:
        profile = load_profile(engine)
        if profile is None:
            errors.append("No hay perfil configurado (profile.id=1). Completa el onboarding primero.")
            _log_run(engine, started_at, jsearch_calls, llm_calls, new_jobs_found, errors)
            return

        can_run, jsearch_used_month, llm_used_today = check_budget(engine)
        if not can_run:
            errors.append(f"Presupuesto JSearch agotado ({jsearch_used_month}/{JSEARCH_MONTHLY_BUDGET} este mes).")
            _log_run(engine, started_at, jsearch_calls, llm_calls, new_jobs_found, errors)
            return

        try:
            variant = get_or_seed_variant(engine, 1, profile)
        except RuntimeError as e:
            errors.append(str(e))
            _log_run(engine, started_at, jsearch_calls, llm_calls, new_jobs_found, errors)
            return

        query = variant["query_text"]
        cutoff = variant.get("last_posted_cutoff_utc")
        remote_only = profile.get("remote_preference") == "remote"

        print(
            f"JSearch query (variante '{variant['query_text']}', id={variant['id']}): "
            f"location='{profile.get('location_preference')}', remote_only={remote_only}, cutoff={cutoff}"
        )
        raw_jobs = search_jobs(query=query, location=profile.get("location_preference"), remote_only=remote_only)
        jsearch_calls += 1

        with engine.begin() as conn:
            for raw in raw_jobs:
                job = normalize_job(raw)
                if not job["external_id"] or not job["apply_link"]:
                    continue

                posted_at = parse_posted_at(job.get("posted_at"))
                if posted_at is not None and (newest_posted_at is None or posted_at > newest_posted_at):
                    newest_posted_at = posted_at

                if cutoff is not None and posted_at is not None and posted_at <= cutoff:
                    continue

                if is_blacklisted(job["title"]) and not any(
                    kw in job["title"].lower() for kw in profile.get("role_family", [])
                ):
                    continue

                existing = conn.execute(
                    text("SELECT id FROM job_offer WHERE external_id = :eid"),
                    {"eid": job["external_id"]},
                ).first()
                if existing:
                    continue

                title_str = safe_text(job.get("title"))
                description_str = safe_text(job.get("description"))
                embed_input = f"{title_str} {description_str}".strip() or "oferta sin descripcion"

                try:
                    job_embedding = embed_text(embed_input)
                except Exception as e:
                    errors.append(f"Error generando embedding para job {job['external_id']}: {e}")
                    continue

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
                new_jobs_found += 1

                conn.execute(
                    text("""
                        INSERT INTO job_score (job_offer_id, profile_id, vector_similarity, llm_evaluated, final_score)
                        VALUES (:job_offer_id, 1, :similarity, FALSE, :final_score)
                        ON CONFLICT (job_offer_id, profile_id) DO NOTHING
                    """),
                    {"job_offer_id": job_offer_id, "similarity": similarity, "final_score": similarity * 100},
                )

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
                            pros = :pros, cons = :cons, missing_requirements = :missing, final_score = :final_score
                        WHERE id = :score_id
                    """),
                    {
                        "llm_score": evaluation["llm_score"],
                        "pros": evaluation["pros"],
                        "cons": evaluation["cons"],
                        "missing": evaluation["missing_requirements"],
                        "final_score": final_score,
                        "score_id": row["score_id"],
                    },
                )

    except Exception:
        errors.append(traceback.format_exc())
    finally:
        if variant is not None:
            try:
                mark_variant_run(engine, variant["id"], newest_posted_at)
            except Exception as e:
                errors.append(f"Error actualizando cutoff de variante {variant.get('id')}: {e}")
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
