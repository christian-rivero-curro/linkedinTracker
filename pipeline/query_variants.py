"""
Gestion de variantes de query de busqueda (tabla search_query_variant).

En vez de una unica query fija por ejecucion del cron, se mantiene una lista de
variantes (roles/skills) editable desde /onboarding. Cada ejecucion selecciona
la variante menos usada recientemente (rotacion auto-regulada por last_run_at),
y lleva un cursor temporal (last_posted_cutoff_utc) por variante para evitar
reprocesar las mismas ofertas entre ejecuciones sucesivas.

Este modulo NO depende de nada mas que app.db.get_engine, para no arriesgar
romper otros modulos existentes que no se han podido inspeccionar en detalle.
"""
from datetime import datetime, timezone

from sqlalchemy import text

MAX_SEED_VARIANTS = 5
DEFAULT_FALLBACK_ROLE = "software engineer"


def get_active_variants(engine, profile_id: int = 1) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM search_query_variant
                WHERE profile_id = :pid AND is_active = TRUE
                ORDER BY order_index ASC
            """),
            {"pid": profile_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def seed_default_variants(engine, profile_id: int, profile: dict) -> None:
    """
    Crea variantes iniciales a partir del CV/formulario si el usuario todavia
    no ha definido ninguna manualmente ni via el boton de IA en /onboarding.
    Es un fallback de arranque, no sustituye a la generacion asistida por IA.
    """
    extracted = profile.get("extracted_json") or {}
    equivalent_roles = [r for r in (extracted.get("equivalent_roles") or []) if r]
    role_family = [r for r in (profile.get("role_family") or []) if r]

    seen = set()
    candidates = []
    for role in equivalent_roles + role_family:
        key = role.strip().lower()
        if key and key not in seen:
            seen.add(key)
            candidates.append(role.strip())

    if not candidates:
        candidates = [DEFAULT_FALLBACK_ROLE]

    candidates = candidates[:MAX_SEED_VARIANTS]

    with engine.begin() as conn:
        for idx, query_text_value in enumerate(candidates):
            conn.execute(
                text("""
                    INSERT INTO search_query_variant (profile_id, query_text, source, order_index)
                    VALUES (:profile_id, :query_text, 'ai', :order_index)
                """),
                {"profile_id": profile_id, "query_text": query_text_value, "order_index": idx},
            )


def pick_next_variant(engine, profile_id: int = 1) -> dict | None:
    """
    Selecciona la variante activa que menos recientemente se ha usado.
    Se auto-regula si se anaden/desactivan variantes entre ejecuciones,
    sin necesidad de llevar un indice de rotacion aparte.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT * FROM search_query_variant
                WHERE profile_id = :pid AND is_active = TRUE
                ORDER BY last_run_at ASC NULLS FIRST, order_index ASC
                LIMIT 1
            """),
            {"pid": profile_id},
        ).mappings().first()
    return dict(row) if row else None


def mark_variant_run(engine, variant_id: int, newest_posted_at: datetime | None) -> None:
    """
    Actualiza last_run_at a ahora, y last_posted_cutoff_utc al timestamp mas
    reciente de las ofertas realmente procesadas en esta ejecucion (o se deja
    igual/ahora si no hubo ofertas nuevas, para no perder cobertura).
    """
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE search_query_variant
                SET last_run_at = :now,
                    last_posted_cutoff_utc = COALESCE(:newest, last_posted_cutoff_utc, :now),
                    updated_at = :now
                WHERE id = :id
            """),
            {"id": variant_id, "newest": newest_posted_at, "now": datetime.now(timezone.utc)},
        )


def get_or_seed_variant(engine, profile_id: int, profile: dict) -> dict:
    """
    Punto de entrada usado por el cron: si no hay ninguna variante (activa o no)
    para el perfil, siembra las iniciales; despues selecciona la variante a usar
    en esta ejecucion.
    """
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM search_query_variant WHERE profile_id = :pid"),
            {"pid": profile_id},
        ).scalar()
    if not count:
        seed_default_variants(engine, profile_id, profile)

    variant = pick_next_variant(engine, profile_id)
    if variant is None:
        # Todas las variantes existentes estan desactivadas: no hay nada que buscar.
        raise RuntimeError(
            "No hay variantes de busqueda activas para el perfil. "
            "Activa al menos una desde /onboarding."
        )
    return variant
