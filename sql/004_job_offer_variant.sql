-- Registra que variante de busqueda encontro cada oferta, para poder mostrarla
-- y filtrar por ella en el dashboard. ON DELETE SET NULL: si se borra la variante
-- (desde /onboarding), las ofertas ya guardadas no se pierden, solo pierden la referencia.

ALTER TABLE job_offer ADD COLUMN IF NOT EXISTS variant_id INTEGER
    REFERENCES search_query_variant(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_job_offer_variant_id ON job_offer(variant_id);
