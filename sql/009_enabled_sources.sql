-- Migración 009: Añadir soporte para selección de fuentes de ofertas por usuario en profile

ALTER TABLE profile ADD COLUMN IF NOT EXISTS enabled_sources TEXT[] DEFAULT '{"linkedin"}';

-- Asegurar que los perfiles existentes tengan al menos 'linkedin' configurado
UPDATE profile
SET enabled_sources = '{"linkedin"}'
WHERE enabled_sources IS NULL OR array_length(enabled_sources, 1) IS NULL;
