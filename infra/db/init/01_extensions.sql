-- Extensions the application depends on.
--
-- Created here, at first container start, rather than in an Alembic migration.
-- CREATE EXTENSION requires superuser, and the application role deliberately
-- does not have it; running this as the bootstrap superuser keeps the runtime
-- role unprivileged.
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector, similarity search
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid() for PK defaults
