-- Variantes de query de busqueda para JSearch, editables desde /onboarding.
-- Permite rotar entre varias combinaciones rol/skill en lugar de una unica query fija,
-- y llevar un cursor temporal por variante para no reprocesar las mismas ofertas entre ejecuciones.

CREATE TABLE IF NOT EXISTS search_query_variant (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    query_text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('ai', 'manual')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    order_index INTEGER NOT NULL DEFAULT 0,
    last_run_at TIMESTAMPTZ,
    last_posted_cutoff_utc TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_query_variant_profile_active
    ON search_query_variant (profile_id, is_active, last_run_at);

COMMENT ON COLUMN search_query_variant.last_posted_cutoff_utc IS
    'Timestamp del job mas reciente procesado la ultima vez que corrio esta variante. Se usa para filtrar del lado del cliente y evitar solapamiento entre ejecuciones.';
