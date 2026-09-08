-- Añade la columna salary_raw a job_offer para guardar el salario o rango salarial como texto (ej. "45.000€ - 55.000€").
ALTER TABLE job_offer ADD COLUMN IF NOT EXISTS salary_raw TEXT;

COMMENT ON COLUMN job_offer.salary_raw IS
    'Rango salarial en texto detectado por el scraper o extraído por el LLM a partir de la descripción (ej. 40.000€ - 50.000€/año).';
