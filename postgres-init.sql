-- =============================================================================
-- .docker/postgres-init.sql
-- Runs once on first container boot (docker-entrypoint-initdb.d)
-- Creates extensions needed by the application
-- =============================================================================

-- uuid-ossp: server-side UUID generation (backup if app layer doesn't set it)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- pg_stat_statements: query performance monitoring (essential for production tuning)
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
