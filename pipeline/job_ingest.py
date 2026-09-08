"""
Logica de insercion COMPARTIDA entre todas las fuentes de descubrimiento de
ofertas (JSearch, scraper de LinkedIn, futuras fuentes). Cada fuente convierte
sus datos crudos a este formato normalizado antes de llamar a
process_and_store_job():

{
    "external_id": str,       # unico por fuente+oferta, ej. "linkedin_4123456789"
    "title": str,
    "company": str | None,
    "location": str | None,
    "remote_type": "remote" | "hybrid" | "onsite" | None,
    "description": str,
    "apply_link": str,
    "source": "linkedin" | "indeed" | "other",
    "salary_min": int | None,
    "salary_max": int | None,
    "posted_at": datetime | str | None,
}

Centralizar esto evita que la logica de dedup/filtros/embedding diverja entre
JSearch y el scraper de LinkedIn. El parametro verbose (por defecto False,
para no ensuciar los logs del cron de JSearch cada 4h) imprime el motivo
exacto por el que se descarta cada oferta - activado por run_linkedin_scrape.py.
"""
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from pipeline.embeddings import embed_text, cosine_similarity, to_pgvector_literal
from pipeline.scoring import is_blacklisted


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


MAX_JOB_AGE_DAYS = max(1, _int_env("JSEARCH_MAX_JOB_AGE_DAYS", 35))


def safe_text(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    return value


def parse_posted_at(value):
    """Parseo defensivo del timestamp de publicacion. Nunca lanza: si no se
    puede interpretar, devuelve None (la oferta se procesa igual, sin filtrar
    por fecha, para no perder posibles matches por un formato inesperado)."""
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


def is_excluded_by_profile(title: str, description: str, profile: dict) -> bool:
    excluded = [kw.lower() for kw in (profile.get("excluded_keywords") or []) if kw]
    if not excluded:
        return False
    haystack = f"{title} {description}".lower()
    return any(kw in haystack for kw in excluded)


def process_and_store_job(
    conn,
    job: dict,
    profile: dict,
    cutoff,
    errors: list,
    variant_id,
    allowed_sources: list[str] | None = None,
    verbose: bool = False,
) -> tuple[bool, object, bool]:
    """
    Inserta una oferta ya normalizada en job_offer/job_score. Aplica, en orden,
    los mismos filtros para CUALQUIER fuente:
      1. Techo absoluto de antiguedad (MAX_JOB_AGE_DAYS).
      2. Cutoff relativo de la variante.
      3. allowed_sources.
      4. Blacklist generica (is_blacklisted) + excluded_keywords del perfil.
      5. Deduplicacion por external_id.

    Devuelve (es_fresca, posted_at, fue_insertada).
    """
    label = job.get("external_id") or job.get("title") or "oferta sin identificar"

    if not job.get("external_id") or not job.get("apply_link"):
        if verbose:
            print(f"  [job_ingest] DESCARTADA '{label}': falta external_id o apply_link.")
        return False, None, False

    posted_at = parse_posted_at(job.get("posted_at"))

    if posted_at is not None:
        max_age_threshold = datetime.now(timezone.utc) - timedelta(days=MAX_JOB_AGE_DAYS)
        if posted_at < max_age_threshold:
            if verbose:
                print(f"  [job_ingest] DESCARTADA '{label}': mas antigua que MAX_JOB_AGE_DAYS={MAX_JOB_AGE_DAYS} dias (posted_at={posted_at}).")
            return False, posted_at, False

    is_fresh = cutoff is None or posted_at is None or posted_at > cutoff
    if not is_fresh:
        if verbose:
            print(f"  [job_ingest] DESCARTADA '{label}': anterior al cutoff de la variante ({cutoff}).")
        return False, posted_at, False

    if allowed_sources and job.get("source") not in allowed_sources:
        if verbose:
            print(f"  [job_ingest] DESCARTADA '{label}': source='{job.get('source')}' no esta en allowed_sources={allowed_sources}.")
        return True, posted_at, False

    title = safe_text(job.get("title"))
    description = safe_text(job.get("description"))

    if is_blacklisted(title) and not any(
        kw in title.lower() for kw in profile.get("role_family", [])
    ):
        if verbose:
            print(f"  [job_ingest] DESCARTADA '{label}': titulo en blacklist generica.")
        return True, posted_at, False

    if is_excluded_by_profile(title, description, profile):
        if verbose:
            print(f"  [job_ingest] DESCARTADA '{label}': coincide con excluded_keywords del perfil.")
        return True, posted_at, False

    user_id = profile.get("user_id")
    profile_id = profile.get("id") or 1

    existing = conn.execute(
        text("SELECT id FROM job_offer WHERE user_id = :uid AND external_id = :eid"),
        {"uid": user_id, "eid": job["external_id"]},
    ).first()
    if existing:
        if verbose:
            print(f"  [job_ingest] DESCARTADA '{label}': ya existe en job_offer del usuario (external_id duplicado, id={existing[0]}).")
        return True, posted_at, False

    embed_input = f"{title} {description}".strip() or "oferta sin descripcion"
    try:
        job_embedding = embed_text(embed_input)
    except Exception as e:
        errors.append(f"Error generando embedding para job {job['external_id']}: {e}")
        if verbose:
            print(f"  [job_ingest] ERROR '{label}': fallo generando embedding: {e}")
        return True, posted_at, False

    similarity = cosine_similarity(job_embedding, profile["embedding"])

    result = conn.execute(
        text("""
            INSERT INTO job_offer (user_id, external_id, title, company, location, remote_type,
                description, apply_link, source, salary_min, salary_max, salary_raw, posted_at, embedding, variant_id)
            VALUES (:user_id, :external_id, :title, :company, :location, :remote_type,
                :description, :apply_link, :source, :salary_min, :salary_max, :salary_raw, :posted_at, CAST(:embedding AS vector), :variant_id)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "external_id": job["external_id"],
            "title": title,
            "company": job.get("company"),
            "location": job.get("location"),
            "remote_type": job.get("remote_type"),
            "description": description,
            "apply_link": job["apply_link"],
            "source": job.get("source", "other"),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "salary_raw": job.get("salary_raw"),
            "posted_at": posted_at,
            "embedding": to_pgvector_literal(job_embedding),
            "variant_id": variant_id,
        },
    )
    job_offer_id = result.scalar()

    conn.execute(
        text("""
            INSERT INTO job_score (job_offer_id, profile_id, user_id, vector_similarity, llm_evaluated, final_score)
            VALUES (:job_offer_id, :profile_id, :user_id, :similarity, FALSE, :final_score)
            ON CONFLICT (job_offer_id, profile_id) DO NOTHING
        """),
        {
            "job_offer_id": job_offer_id,
            "profile_id": profile_id,
            "user_id": user_id,
            "similarity": similarity,
            "final_score": similarity * 100,
        },
    )
    if verbose:
        print(f"  [job_ingest] INSERTADA '{label}' (job_offer.id={job_offer_id}, user_id={user_id}, similitud={similarity:.3f}).")
    return True, posted_at, True

