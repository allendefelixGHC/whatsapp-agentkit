-- scripts/add_productor_column.sql
-- Agrega columna productor a tabla propiedades existente
-- Seguro para re-ejecutar (IF NOT EXISTS)

ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS productor TEXT;
