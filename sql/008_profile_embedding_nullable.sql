-- Migración 008: Permitir que profile.embedding sea NULL
-- Evita caídas por OOM / 502 Bad Gateway en entornos web con memoria limitada (como Render free tier de 512MB).
-- El pipeline en GitHub Actions (7GB RAM) genera y persiste el vector automáticamente.

ALTER TABLE profile ALTER COLUMN embedding DROP NOT NULL;
