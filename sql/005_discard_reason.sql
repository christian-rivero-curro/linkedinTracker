-- Motivo opcional al descartar una oferta desde el dashboard.
ALTER TABLE job_score ADD COLUMN IF NOT EXISTS discard_reason TEXT;
