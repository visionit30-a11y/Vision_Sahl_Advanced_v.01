-- Administrator-only provisioning; no LOGIN, password, data access or purge execution here.
-- Run against the intended Sahl cluster before migration 0016. Fail on unsafe existing roles.
BEGIN;
DO $provision$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='sahl_security_maintenance') THEN
        CREATE ROLE sahl_security_maintenance NOLOGIN NOSUPERUSER NOBYPASSRLS
            NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname='sahl_security_maintenance'
          AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication)
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members m
        JOIN pg_catalog.pg_roles r ON r.oid=m.member
        WHERE r.rolname='sahl_security_maintenance'
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_shdepend d
        JOIN pg_catalog.pg_roles r ON r.oid=d.refobjid
        WHERE r.rolname='sahl_security_maintenance' AND d.deptype='o'
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname IN ('sahl_app','sahl_migrator')
          AND pg_catalog.pg_has_role(r.oid,'sahl_security_maintenance','MEMBER')
    ) THEN
        RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='security_maintenance_provisioning_denied';
    END IF;
END
$provision$;
COMMIT;
