"""
Gestion de variantes de query de busqueda (tabla search_query_variant).

En vez de una unica query fija por ejecucion del cron, se mantiene una lista de
variantes (roles/skills) editable desde /onboarding. Cada ejecucion selecciona
la variante menos usada recientemente (rotacion auto-regulada por last_run_at),
y lleva un cursor temporal (last_posted_cutoff_utc) por variante para evitar
reprocesar las mismas ofertas entre ejecuciones sucesivas.

Tambien incluye la generacion asistida por IA de variantes (boton en
/onboarding): siempre en modo 'append', nunca sobrescribe lo que el usuario
ya haya definido o editado a mano.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from pipeline.llm_client import call_llm_json

MAX_SEED_VARIANTS = 5
MAX_AI_VARIANTS = 6
DEFAULT_FALLBACK_ROLE = "software engineer"
VARIANTS_PROMPT_PATH = Path(__file__).parent / "prompts" / "generate_variants.txt"


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


def get_all_variants(engine, profile_id: int = 1) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM search_query_variant
                WHERE profile_id = :pid
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
    equivalent_roles_raw = extracted.get("equivalent_roles")
    role_family_raw = profile.get("role_family")
    equivalent_roles = [r for r in equivalent_roles_raw if isinstance(r, str) and r.strip()] if isinstance(equivalent_roles_raw, list) else []
    role_family = [r for r in role_family_raw if isinstance(r, str) and r.strip()] if isinstance(role_family_raw, list) else []

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


def generate_variants_via_llm(profile: dict) -> list[str]:
    """
    Genera sugerencias de variantes de busqueda a partir del CV/formulario,
    usando el mismo modelo :free que la extraccion de CV. No toca la base de
    datos, solo devuelve la lista de strings sugeridos.

    Robusto a desviaciones de formato del LLM: si 'variants' no es una lista
    (ej. llega como string o numero), o contiene elementos que no son str,
    se descartan en vez de propagar un TypeError o iterar caracteres sueltos.
    """
    model = os.environ.get("OPENROUTER_MODEL_EXTRACTION", "minimax/minimax-m2.7:free")
    prompt_template = VARIANTS_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        profile_json=json.dumps(profile.get("extracted_json") or {}, ensure_ascii=False),
        role_family=", ".join(r for r in (profile.get("role_family") or []) if isinstance(r, str)),
    )
    result = call_llm_json(model, prompt)
    variants = result.get("variants") if isinstance(result, dict) else None
    if not isinstance(variants, list):
        variants = []
    cleaned = [v.strip() for v in variants if isinstance(v, str) and v.strip()]
    return cleaned[:MAX_AI_VARIANTS]


def add_ai_variants(engine, profile_id: int, variants: list[str]) -> int:
    """
    Anade las variantes generadas por IA como filas nuevas (append). Nunca
    sobrescribe ni desactiva lo que el usuario ya tenga configurado a mano;
    ignora silenciosamente duplicados exactos (case-insensitive) ya existentes.
    Devuelve cuantas variantes nuevas se insertaron realmente.
    """
    if not variants:
        return 0
    with engine.connect() as conn:
        max_order = conn.execute(
            text("SELECT COALESCE(MAX(order_index), -1) FROM search_query_variant WHERE profile_id = :pid"),
            {"pid": profile_id},
        ).scalar()

    inserted = 0
    with engine.begin() as conn:
        for offset, query_text_value in enumerate(variants):
            existing = conn.execute(
                text("""
                    SELECT id FROM search_query_variant
                    WHERE profile_id = :pid AND lower(query_text) = lower(:qt)
                """),
                {"pid": profile_id, "qt": query_text_value},
            ).first()
            if existing:
                continue
            conn.execute(
                text("""
                    INSERT INTO search_query_variant (profile_id, query_text, source, order_index)
                    VALUES (:pid, :qt, 'ai', :order_index)
                """),
                {"pid": profile_id, "qt": query_text_value, "order_index": max_order + 1 + offset},
            )
            inserted += 1
    return inserted
