-- Migración 011: Añadir estado 'interview' ('entrevista') a la tabla job_score
ALTER TABLE job_score DROP CONSTRAINT IF EXISTS job_score_status_check;
ALTER TABLE job_score ADD CONSTRAINT job_score_status_check CHECK (status IN ('new', 'viewed', 'applied', 'solicitada', 'interview', 'entrevista', 'discarded'));
