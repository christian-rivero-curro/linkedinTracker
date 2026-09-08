-- Migración 007: Soporte Multi-Usuario, Autenticación y Aislamiento de Datos

-- 1. Tabla de usuarios de la aplicación
CREATE TABLE IF NOT EXISTS app_user (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Limpieza de datos antiguos para arrancar desde cero de forma limpia
TRUNCATE TABLE job_score, job_offer, search_query_variant, profile CASCADE;

-- 3. Añadir user_id a profile (1 perfil por usuario)
ALTER TABLE profile ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES app_user(id) ON DELETE CASCADE;
ALTER TABLE profile DROP CONSTRAINT IF EXISTS profile_user_id_key;
ALTER TABLE profile ADD CONSTRAINT profile_user_id_key UNIQUE (user_id);

-- 4. Añadir user_id a search_query_variant y hacer profile_id opcional
ALTER TABLE search_query_variant ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES app_user(id) ON DELETE CASCADE;
ALTER TABLE search_query_variant ALTER COLUMN profile_id DROP NOT NULL;


-- 5. Añadir user_id a job_offer y permitir vacantes aisladas por usuario
ALTER TABLE job_offer ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES app_user(id) ON DELETE CASCADE;
-- Eliminar la restricción de external_id global para que cada usuario tenga sus vacantes independientes
ALTER TABLE job_offer DROP CONSTRAINT IF EXISTS job_offer_external_id_key;
ALTER TABLE job_offer DROP CONSTRAINT IF EXISTS job_offer_user_external_unique;
ALTER TABLE job_offer ADD CONSTRAINT job_offer_user_external_unique UNIQUE (user_id, external_id);

-- 6. Añadir user_id a job_score
ALTER TABLE job_score ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES app_user(id) ON DELETE CASCADE;

-- 7. Índices de rendimiento
CREATE INDEX IF NOT EXISTS idx_profile_user_id ON profile(user_id);
CREATE INDEX IF NOT EXISTS idx_variant_user_id ON search_query_variant(user_id);
CREATE INDEX IF NOT EXISTS idx_job_offer_user_id ON job_offer(user_id);
CREATE INDEX IF NOT EXISTS idx_job_score_user_id ON job_score(user_id);
