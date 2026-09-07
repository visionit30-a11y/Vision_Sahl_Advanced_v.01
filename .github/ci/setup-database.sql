-- CI database roles.
--
-- Two roles, deliberately: a table owner bypasses row level security unless the
-- table forces it, so if migrations and the application shared one role every
-- isolation policy written in Phase 2A would be silently inert and its tests
-- would pass for the wrong reason.
--
--   sahl_migrator  owns the schema and runs Alembic
--   sahl_app       owns nothing and runs the application
--
-- The passwords below are not secrets: this database lives only inside one
-- ephemeral CI job on a runner that is destroyed afterwards, and nothing
-- outside that job can reach it. They are never used anywhere else.

CREATE ROLE sahl_migrator LOGIN PASSWORD 'ci_migrator_password'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

CREATE ROLE sahl_app LOGIN PASSWORD 'ci_app_password'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

GRANT CONNECT ON DATABASE sahl_ci TO sahl_migrator, sahl_app;

-- CREATE on this database permits schemas, not new databases or role changes.
-- Runtime never receives this privilege, directly or through PUBLIC.
REVOKE CREATE ON DATABASE sahl_ci FROM PUBLIC, sahl_app;
GRANT CREATE ON DATABASE sahl_ci TO sahl_migrator;

-- The migrator owns the schema so Alembic can create objects in it.
ALTER SCHEMA public OWNER TO sahl_migrator;

-- The application may resolve the schema; each table must grant its needed
-- operations explicitly. Runtime may never own or
-- create an object in it. CREATE is revoked from PUBLIC explicitly rather than
-- left to the server default: a role that can create an object owns it, and an
-- owner bypasses row level security unless the table forces it. The local
-- provisioning in 01-setup.ps1 does the same, so the two are identical.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO sahl_app;

-- No speculative access to future tables or sequences.
ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA public
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM sahl_app;

ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA public
    REVOKE USAGE, SELECT ON SEQUENCES FROM sahl_app;
