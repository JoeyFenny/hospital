-- Enable trigram for better ILIKE performance
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- Enable earthdistance/cube for spatial indexing on lat/lon
CREATE EXTENSION IF NOT EXISTS cube;
CREATE EXTENSION IF NOT EXISTS earthdistance;

CREATE TABLE IF NOT EXISTS providers (
    id SERIAL PRIMARY KEY,
    provider_id VARCHAR(32) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    city VARCHAR(128),
    state VARCHAR(8),
    zip_code VARCHAR(16),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_providers_zip ON providers(zip_code);
CREATE INDEX IF NOT EXISTS idx_providers_state ON providers(state);
-- GiST index using earthdistance to accelerate radius queries on lat/lon
CREATE INDEX IF NOT EXISTS idx_providers_ll_earth ON providers USING gist (ll_to_earth(latitude, longitude));

CREATE TABLE IF NOT EXISTS procedures (
    id SERIAL PRIMARY KEY,
    provider_id VARCHAR(32) NOT NULL REFERENCES providers(provider_id) ON DELETE CASCADE,
    ms_drg_definition VARCHAR(255) NOT NULL,
    total_discharges INT,
    average_covered_charges NUMERIC(14,2),
    average_total_payments NUMERIC(14,2),
    average_medicare_payments NUMERIC(14,2),
    CONSTRAINT uq_procedure_per_provider_drg UNIQUE(provider_id, ms_drg_definition)
);

CREATE INDEX IF NOT EXISTS idx_procedures_drg ON procedures(ms_drg_definition);
CREATE INDEX IF NOT EXISTS idx_procedures_drg_trgm ON procedures USING GIN (ms_drg_definition gin_trgm_ops);

CREATE TABLE IF NOT EXISTS ratings (
    id SERIAL PRIMARY KEY,
    provider_id VARCHAR(32) NOT NULL REFERENCES providers(provider_id) ON DELETE CASCADE,
    rating INT NOT NULL,
    CONSTRAINT uq_rating_per_provider UNIQUE(provider_id)
);

