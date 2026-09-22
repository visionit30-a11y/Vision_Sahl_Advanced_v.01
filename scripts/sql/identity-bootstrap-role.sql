DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='sahl_identity_bootstrap') THEN
        CREATE ROLE sahl_identity_bootstrap NOLOGIN NOSUPERUSER NOBYPASSRLS
            NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname='sahl_identity_bootstrap'
          AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication)
    ) THEN
        RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='identity_bootstrap_capability_invalid';
    END IF;
END
$$;
