-- scripts/create_propiedades_table.sql
-- Tabla propiedades para AgentKit (Inmobiliaria Bertero)
-- Fuente: inspección del HTML de inmobiliariabertero.com.ar (2026-03-28)
--
-- Instrucciones:
--   1. Ve a supabase.com -> tu proyecto -> SQL Editor
--   2. Pega este script completo y ejecuta (Run)
--   3. La tabla se crea solo si no existe (IF NOT EXISTS es seguro para re-ejecutar)

CREATE TABLE IF NOT EXISTS propiedades (
    id              BIGSERIAL PRIMARY KEY,
    propiedad_id    TEXT UNIQUE NOT NULL,       -- ID numérico de la URL, ej: "7778974"
    link            TEXT NOT NULL,              -- Path relativo, ej: "/p/7778974-departamento-..."
    tipo            TEXT,                       -- "departamento", "casa", "terreno", etc.
    operacion       TEXT,                       -- "venta" o "alquiler"
    zona            TEXT,                       -- Barrio/zona, ej: "Nueva Córdoba"
    direccion       TEXT,                       -- Dirección de la propiedad
    precio          TEXT,                       -- Precio legible, ej: "USD 55.000"
    precio_num      INTEGER DEFAULT 0,          -- Precio numérico para filtros de rango, ej: 55000
    superficie      TEXT,                       -- Superficie del listado, ej: "68 m²"
    ambientes       INTEGER,                    -- Número de ambientes
    dormitorios     INTEGER,                    -- Número de dormitorios
    banos           INTEGER,                    -- Número de baños
    sup_cubierta    TEXT,                       -- Superficie cubierta del detalle, ej: "79 m²"
    sup_total       TEXT,                       -- Superficie total construida, ej: "358 m²"
    antiguedad      TEXT,                       -- Antigüedad, ej: "36 Años"
    expensas        TEXT,                       -- Expensas mensuales, ej: "$ 109.000"
    descripcion     TEXT,                       -- Descripción de la propiedad (máx 1000 chars)
    productor       TEXT,                       -- Nombre del productor/asesor asignado
    scraped_at      TIMESTAMPTZ DEFAULT NOW()   -- Timestamp del último scraping
);

-- Índice para filtros por tipo de operación (venta/alquiler)
CREATE INDEX IF NOT EXISTS idx_propiedades_operacion ON propiedades (operacion);

-- Índice para filtros por tipo de propiedad (departamento/casa/etc)
CREATE INDEX IF NOT EXISTS idx_propiedades_tipo ON propiedades (tipo);

-- Índice para filtros de rango de precio
CREATE INDEX IF NOT EXISTS idx_propiedades_precio ON propiedades (precio_num);
