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

-- The migrator owns the schema so Alembic can create objects in it.
ALTER SCHEMA public OWNER TO sahl_migrator;

-- The application may use the schema and work with rows, and may never own or
-- create an object in it.
GRANT USAGE ON SCHEMA public TO sahl_app;

ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sahl_app;

ALTER DEFAULT PRIVILEGES FOR ROLE sahl_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO sahl_app;
