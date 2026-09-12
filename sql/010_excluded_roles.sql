-- Migración 010: Añadir columna excluded_roles a la tabla profile para puestos/trabajos no deseados
ALTER TABLE profile ADD COLUMN IF NOT EXISTS excluded_roles TEXT[] DEFAULT '{}';
ALTER TABLE profile ADD COLUMN IF NOT EXISTS excluded_keywords TEXT[] DEFAULT '{}';
