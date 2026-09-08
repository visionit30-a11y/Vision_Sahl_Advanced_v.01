# ruff: noqa: E501
"""Harden the closed audit event writer without changing security semantics.

Revision ID: 0014_security_audit_contract
Revises: 0013_auth_http_projections

Old rows remain unchanged. NOT VALID constraints enforce new rows while retaining
legacy metadata. Role and retention events remain reserved until scoped writers
are approved; migrator cannot read FORCE RLS roles using the runtime policy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_security_audit_contract"
down_revision: str | None = "0013_auth_http_projections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_SIGNATURE = "auth.append_security_event(uuid,text,text,text,uuid,uuid,uuid,bytea,uuid,uuid,uuid,text,text,smallint,bigint)"
LEGACY_SIGNATURE = "auth.record_security_event(uuid,text,text,text,uuid,uuid,uuid,bytea,text)"
VALIDATOR_SIGNATURE = "auth.validate_security_event_insert()"
OLD_EVENT_TYPES = (
    "login_success",
    "login_failure",
    "logout",
    "session_revoked",
    "all_sessions_revoked",
    "password_changed",
    "password_reset_requested",
    "password_reset_completed",
    "membership_denied",
    "tenant_switch",
    "throttling_triggered",
)
RESERVED_EVENT_TYPES = (
    "role_created",
    "role_updated",
    "role_disabled",
    "role_permission_assigned",
    "role_permission_removed",
    "membership_role_assigned",
    "membership_role_removed",
    "security_events_pruned",
)
NEW_COLUMNS = (
    "role_id",
    "target_membership_id",
    "permission_id",
    "subject_kind",
    "subject_key_id",
    "affected_count",
)

# Frozen snapshot: no runtime imports are permitted in this migration.
AUDIT_CHECKS = {
    "event_type_allowed": "event_type IN "
    "('all_sessions_revoked','authorization_denied','csrf_rejected','login_failure','login_success','logout','membership_denied','membership_role_assigned','membership_role_removed','origin_rejected','password_changed','password_reset_completed','password_reset_requested','role_created','role_disabled','role_permission_assigned','role_permission_removed','role_updated','security_events_pruned','session_revoked','tenant_switch','throttling_triggered')",
    "result_allowed": "result IN ('success','failure','denied')",
    "event_contract": "(event_type = 'login_success' AND result = 'success' AND reason_code IS NULL) OR "
    "(event_type = 'login_failure' AND result = 'failure' AND (reason_code IS NULL OR "
    "reason_code IN ('dependency_unavailable','invalid_credentials'))) OR (event_type = "
    "'logout' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('logout'))) "
    "OR (event_type = 'session_revoked' AND result = 'success' AND (reason_code IS NULL OR "
    "reason_code IN ('concurrent_limit','logout','password_reset','revoke_all'))) OR "
    "(event_type = 'all_sessions_revoked' AND result = 'success' AND (reason_code IS NULL OR "
    "reason_code IN ('password_reset','revoke_all'))) OR (event_type = 'password_changed' AND "
    "result = 'success' AND (reason_code IS NULL OR reason_code IN ('password_reset'))) OR "
    "(event_type = 'password_reset_requested' AND result = 'success' AND reason_code IS NULL) "
    "OR (event_type = 'password_reset_completed' AND result = 'success' AND (reason_code IS "
    "NULL OR reason_code IN ('password_reset'))) OR (event_type = 'membership_denied' AND "
    "result = 'denied' AND (reason_code IS NULL OR reason_code IN "
    "('dependency_unavailable','membership_unavailable'))) OR (event_type = 'tenant_switch' "
    "AND result = 'success' AND reason_code IS NULL) OR (event_type = 'throttling_triggered' "
    "AND result = 'denied' AND (reason_code IS NULL OR reason_code IN "
    "('csrf_bootstrap','login_ip','login_ip_username','login_username','reset_ip','reset_username'))) "
    "OR (event_type = 'authorization_denied' AND result = 'denied' AND (reason_code IS NULL "
    "OR reason_code IN "
    "('dependency_unavailable','membership_unavailable','permission_denied'))) OR (event_type "
    "= 'csrf_rejected' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN "
    "('csrf_invalid','csrf_missing','csrf_stale'))) OR (event_type = 'origin_rejected' AND "
    "result = 'denied' AND (reason_code IS NULL OR reason_code IN ('origin_denied'))) OR "
    "(event_type = 'role_created' AND result = 'success' AND reason_code IS NULL) OR "
    "(event_type = 'role_updated' AND result = 'success' AND reason_code IS NULL) OR "
    "(event_type = 'role_disabled' AND result = 'success' AND reason_code IS NULL) OR "
    "(event_type = 'role_permission_assigned' AND result = 'success' AND reason_code IS NULL) "
    "OR (event_type = 'role_permission_removed' AND result = 'success' AND reason_code IS "
    "NULL) OR (event_type = 'membership_role_assigned' AND result = 'success' AND reason_code "
    "IS NULL) OR (event_type = 'membership_role_removed' AND result = 'success' AND "
    "reason_code IS NULL) OR (event_type = 'security_events_pruned' AND result = 'success' "
    "AND (reason_code IS NULL OR reason_code IN ('retention_expired')))",
    "event_id_uuid7": "id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
    "correlation_id_format": "correlation_id ~ "
    "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
    "identity_shape": "(user_id IS NOT NULL OR (session_id IS NULL AND membership_id IS NULL)) AND (event_type "
    "NOT IN "
    "('tenant_switch','membership_role_assigned','membership_role_removed','role_created','role_disabled','role_permission_assigned','role_permission_removed','role_updated') "
    "OR (user_id IS NOT NULL AND session_id IS NOT NULL AND membership_id IS NOT NULL))",
    "role_shape": "(event_type IN "
    "('membership_role_assigned','membership_role_removed','role_created','role_disabled','role_permission_assigned','role_permission_removed','role_updated')) "
    "= (role_id IS NOT NULL)",
    "target_membership_shape": "(event_type IN ('membership_role_assigned','membership_role_removed')) = "
    "(target_membership_id IS NOT NULL)",
    "permission_catalog": "permission_id IS NULL OR permission_id IN "
    "('platform.tenants.manage','platform.tenants.read','platform.ui_settings.manage','tenant.memberships.manage','tenant.memberships.read','tenant.roles.manage','tenant.roles.read','tenant.ui_settings.manage','tenant.user_ui_settings.manage_self')",
    "permission_shape": "(event_type NOT IN ('role_permission_assigned','role_permission_removed') OR "
    "permission_id IS NOT NULL) AND (permission_id IS NULL OR event_type IN "
    "('authorization_denied','role_permission_assigned','role_permission_removed'))",
    "subject_shape": "(subject_digest IS NULL AND subject_kind IS NULL AND subject_key_id IS NULL) OR "
    "(subject_digest IS NOT NULL AND octet_length(subject_digest) = 32 AND subject_kind IS NOT "
    "NULL AND subject_kind IN ('login_ip','login_username','reset_ip','reset_username') AND "
    "subject_key_id IS NOT NULL AND subject_key_id BETWEEN 1 AND 32767)",
    "affected_count_shape": "(event_type <> 'security_events_pruned' AND affected_count IS NULL) OR (event_type "
    "= 'security_events_pruned' AND affected_count IS NOT NULL AND affected_count >= 0 "
    "AND user_id IS NULL AND session_id IS NULL AND membership_id IS NULL AND role_id "
    "IS NULL AND target_membership_id IS NULL AND subject_digest IS NULL AND "
    "subject_kind IS NULL AND subject_key_id IS NULL)",
}

# Exact legacy definitions for a non-destructive downgrade.
LEGACY_FUNCTIONS = (
    """CREATE OR REPLACE FUNCTION auth.request_password_reset(p_email text,p_digest bytea,p_token uuid,p_event uuid,p_correlation text)
      RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$
      DECLARE v_user uuid; BEGIN SELECT id INTO v_user FROM auth.users WHERE normalized_email=p_email AND status='active'::auth.user_status;
       IF v_user IS NULL THEN RETURN false; END IF;
       UPDATE auth.password_reset_tokens SET revoked_at=clock_timestamp() WHERE user_id=v_user AND consumed_at IS NULL AND revoked_at IS NULL;
       INSERT INTO auth.password_reset_tokens(id,user_id,token_digest,created_at,expires_at) VALUES(p_token,v_user,p_digest,clock_timestamp(),clock_timestamp()+interval '15 minutes');
       INSERT INTO auth.security_events(id,event_type,result,user_id,correlation_id,created_at) VALUES(p_event,'password_reset_requested','success',v_user,p_correlation,clock_timestamp()); RETURN true; END $f$""",
    """CREATE OR REPLACE FUNCTION auth.complete_password_reset(p_digest bytea,p_hash text,p_event uuid,p_correlation text)
      RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$
      DECLARE v_token auth.password_reset_tokens%ROWTYPE; BEGIN
       SELECT * INTO v_token FROM auth.password_reset_tokens WHERE token_digest=p_digest AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>clock_timestamp() FOR UPDATE;
       IF NOT FOUND THEN RETURN false; END IF;
       UPDATE auth.password_reset_tokens SET consumed_at=clock_timestamp() WHERE id=v_token.id;
       UPDATE auth.password_reset_tokens SET revoked_at=clock_timestamp() WHERE user_id=v_token.user_id AND id<>v_token.id AND consumed_at IS NULL AND revoked_at IS NULL;
       UPDATE auth.password_credentials SET password_hash=p_hash,credential_version=credential_version+1,changed_at=clock_timestamp() WHERE user_id=v_token.user_id;
       IF NOT FOUND THEN RAISE EXCEPTION 'credential_missing'; END IF;
       UPDATE auth.users SET security_version=security_version+1,updated_at=clock_timestamp() WHERE id=v_token.user_id;
       UPDATE auth.sessions SET revoked_at=clock_timestamp(),revoked_reason='password_reset' WHERE user_id=v_token.user_id AND revoked_at IS NULL;
       INSERT INTO auth.security_events(id,event_type,result,user_id,correlation_id,created_at) VALUES(p_event,'password_reset_completed','success',v_token.user_id,p_correlation,clock_timestamp()); RETURN true; END $f$""",
    """CREATE OR REPLACE FUNCTION auth.record_security_event(p_id uuid,p_type text,p_result text,p_reason text,p_user uuid,p_session uuid,p_membership uuid,p_subject bytea,p_correlation text)
      RETURNS void LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$
      INSERT INTO auth.security_events(id,event_type,result,reason_code,user_id,session_id,membership_id,subject_digest,correlation_id,created_at)
      SELECT p_id,p_type,p_result,p_reason,p_user,
       CASE WHEN EXISTS(SELECT 1 FROM auth.sessions s WHERE s.id=p_session AND (p_user IS NULL OR s.user_id=p_user)) THEN p_session END,
       CASE WHEN EXISTS(SELECT 1 FROM auth.tenant_memberships m WHERE m.id=p_membership AND (p_user IS NULL OR m.user_id=p_user)) THEN p_membership END,
       p_subject,p_correlation,clock_timestamp() $f$""",
)

# Only the audit INSERT changes; reset business operations remain identical.
RESET_FUNCTIONS = (
    """CREATE OR REPLACE FUNCTION auth.request_password_reset(p_email text,p_digest bytea,p_token uuid,p_event uuid,p_correlation text)
      RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$
      DECLARE v_user uuid; BEGIN SELECT id INTO v_user FROM auth.users WHERE normalized_email=p_email AND status='active'::auth.user_status;
       IF v_user IS NULL THEN RETURN false; END IF;
       UPDATE auth.password_reset_tokens SET revoked_at=clock_timestamp() WHERE user_id=v_user AND consumed_at IS NULL AND revoked_at IS NULL;
       INSERT INTO auth.password_reset_tokens(id,user_id,token_digest,created_at,expires_at) VALUES(p_token,v_user,p_digest,clock_timestamp(),clock_timestamp()+interval '15 minutes');
       PERFORM auth.record_security_event(p_event,'password_reset_requested','success',NULL,v_user,NULL,NULL,NULL,p_correlation); RETURN true; END $f$""",
    """CREATE OR REPLACE FUNCTION auth.complete_password_reset(p_digest bytea,p_hash text,p_event uuid,p_correlation text)
      RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$
      DECLARE v_token auth.password_reset_tokens%ROWTYPE; BEGIN
       SELECT * INTO v_token FROM auth.password_reset_tokens WHERE token_digest=p_digest AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>clock_timestamp() FOR UPDATE;
       IF NOT FOUND THEN RETURN false; END IF;
       UPDATE auth.password_reset_tokens SET consumed_at=clock_timestamp() WHERE id=v_token.id;
       UPDATE auth.password_reset_tokens SET revoked_at=clock_timestamp() WHERE user_id=v_token.user_id AND id<>v_token.id AND consumed_at IS NULL AND revoked_at IS NULL;
       UPDATE auth.password_credentials SET password_hash=p_hash,credential_version=credential_version+1,changed_at=clock_timestamp() WHERE user_id=v_token.user_id;
       IF NOT FOUND THEN RAISE EXCEPTION 'credential_missing'; END IF;
       UPDATE auth.users SET security_version=security_version+1,updated_at=clock_timestamp() WHERE id=v_token.user_id;
       UPDATE auth.sessions SET revoked_at=clock_timestamp(),revoked_reason='password_reset' WHERE user_id=v_token.user_id AND revoked_at IS NULL;
       PERFORM auth.record_security_event(p_event,'password_reset_completed','success',NULL,v_token.user_id,NULL,NULL,NULL,p_correlation); RETURN true; END $f$""",
)


def _quoted(values: Sequence[str]) -> str:
    return ",".join("'" + value + "'" for value in values)


def upgrade() -> None:
    for column in (
        sa.Column("role_id", postgresql.UUID(as_uuid=True)),
        sa.Column("target_membership_id", postgresql.UUID(as_uuid=True)),
        sa.Column("permission_id", sa.String(120)),
        sa.Column("subject_kind", sa.String(32)),
        sa.Column("subject_key_id", sa.SmallInteger()),
        sa.Column("affected_count", sa.BigInteger()),
    ):
        op.add_column("security_events", column, schema="auth")
    op.drop_constraint(
        op.f("ck_security_events_event_type_allowed"),
        "security_events",
        schema="auth",
        type_="check",
    )
    op.create_check_constraint(
        "event_type_allowed",
        "security_events",
        AUDIT_CHECKS["event_type_allowed"],
        schema="auth",
    )
    for name, expression in AUDIT_CHECKS.items():
        if name not in {"event_type_allowed", "result_allowed"}:
            op.execute(
                f"ALTER TABLE auth.security_events ADD CONSTRAINT ck_security_events_{name} CHECK ({expression}) NOT VALID"
            )

    # Validate once at append time. No foreign keys/cascades can erase history.
    # Locks preserve verified links until this security operation commits.
    # Revoked/inactive rows remain valid historical references.
    event_shape = " AND ".join(f"({expression})" for expression in AUDIT_CHECKS.values())
    reserved = _quoted(RESERVED_EVENT_TYPES)
    op.execute(f"""
        CREATE FUNCTION auth.validate_security_event_insert()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        AS $function$
        DECLARE
            v_valid boolean;
            v_session_user uuid;
            v_selected_membership uuid;
            v_membership_user uuid;
        BEGIN
            IF NEW.event_type IN ({reserved}) THEN
                RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';
            END IF;
            SELECT {event_shape} INTO v_valid FROM (SELECT NEW.*) AS event_record;
            IF v_valid IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';
            END IF;
            IF NEW.user_id IS NOT NULL THEN
                PERFORM 1 FROM auth.users WHERE id = NEW.user_id FOR KEY SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';
                END IF;
            END IF;
            IF NEW.session_id IS NOT NULL THEN
                SELECT user_id, selected_membership_id INTO v_session_user, v_selected_membership
                FROM auth.sessions WHERE id = NEW.session_id FOR SHARE;
                IF NOT FOUND OR v_session_user IS DISTINCT FROM NEW.user_id THEN
                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';
                END IF;
                IF NEW.membership_id IS NOT NULL AND v_selected_membership IS DISTINCT FROM NEW.membership_id THEN
                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';
                END IF;
            END IF;
            IF NEW.membership_id IS NOT NULL THEN
                SELECT user_id INTO v_membership_user
                FROM auth.tenant_memberships WHERE id = NEW.membership_id FOR KEY SHARE;
                IF NOT FOUND OR v_membership_user IS DISTINCT FROM NEW.user_id THEN
                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';
                END IF;
            END IF;
            NEW.created_at := clock_timestamp();
            RETURN NEW;
        END
        $function$;
    """)
    op.execute(f"ALTER FUNCTION {VALIDATOR_SIGNATURE} OWNER TO sahl_migrator")
    op.execute(f"REVOKE ALL ON FUNCTION {VALIDATOR_SIGNATURE} FROM PUBLIC, sahl_app")
    op.execute("""
        CREATE TRIGGER security_event_insert_guard BEFORE INSERT ON auth.security_events
        FOR EACH ROW EXECUTE FUNCTION auth.validate_security_event_insert()
    """)
    op.execute("""
        CREATE FUNCTION auth.append_security_event(
            p_id uuid, p_type text, p_result text, p_reason text,
            p_user uuid, p_session uuid, p_membership uuid, p_subject bytea,
            p_correlation uuid, p_role uuid, p_target_membership uuid,
            p_permission text, p_subject_kind text, p_subject_key_id smallint,
            p_affected_count bigint
        ) RETURNS void LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
        AS $function$
            INSERT INTO auth.security_events(
                id, event_type, result, reason_code, user_id, session_id,
                membership_id, subject_digest, correlation_id, created_at,
                role_id, target_membership_id, permission_id, subject_kind,
                subject_key_id, affected_count
            ) VALUES (
                p_id, p_type, p_result, p_reason, p_user, p_session,
                p_membership, p_subject, p_correlation::text, clock_timestamp(),
                p_role, p_target_membership, p_permission, p_subject_kind,
                p_subject_key_id, p_affected_count
            )
        $function$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION auth.record_security_event(
            p_id uuid, p_type text, p_result text, p_reason text,
            p_user uuid, p_session uuid, p_membership uuid, p_subject bytea,
            p_correlation text
        ) RETURNS void LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog
        AS $function$
            SELECT auth.append_security_event(
                p_id, p_type, p_result, p_reason, p_user, p_session,
                p_membership, p_subject, gen_random_uuid(), NULL, NULL,
                NULL, NULL, NULL, NULL
            )
        $function$;
    """)
    for definition in RESET_FUNCTIONS:
        op.execute(definition)
    for signature in (
        APPEND_SIGNATURE,
        LEGACY_SIGNATURE,
        "auth.request_password_reset(text,bytea,uuid,uuid,text)",
        "auth.complete_password_reset(bytea,text,uuid,text)",
    ):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO sahl_migrator")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sahl_app")
    op.execute("REVOKE ALL ON TABLE auth.security_events FROM PUBLIC, sahl_app")


def downgrade() -> None:
    # Never erase new events or extension metadata just to make rollback pass.
    # A compatible history remains byte-for-byte unchanged.
    # Serialize the compatibility check with all appends until DDL commits.
    op.execute("LOCK TABLE auth.security_events IN ACCESS EXCLUSIVE MODE")
    old_types = _quoted(OLD_EVENT_TYPES)
    extension_present = " OR ".join(f"{column} IS NOT NULL" for column in NEW_COLUMNS)
    op.execute(f"""
        DO $block$ BEGIN
            IF EXISTS (
                SELECT 1 FROM auth.security_events
                WHERE event_type NOT IN ({old_types}) OR {extension_present}
            ) THEN
                RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'audit_downgrade_requires_compatible_history';
            END IF;
        END $block$;
    """)
    for definition in LEGACY_FUNCTIONS:
        op.execute(definition)
    op.execute(f"DROP FUNCTION {APPEND_SIGNATURE}")
    op.execute("DROP TRIGGER security_event_insert_guard ON auth.security_events")
    op.execute(f"DROP FUNCTION {VALIDATOR_SIGNATURE}")
    for name in AUDIT_CHECKS:
        if name != "result_allowed":
            op.drop_constraint(
                op.f(f"ck_security_events_{name}"),
                "security_events",
                schema="auth",
                type_="check",
            )
    op.create_check_constraint(
        "event_type_allowed",
        "security_events",
        f"event_type IN ({old_types})",
        schema="auth",
    )
    for column in reversed(NEW_COLUMNS):
        op.drop_column("security_events", column, schema="auth")
