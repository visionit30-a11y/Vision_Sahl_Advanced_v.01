# ruff: noqa: E501
"""Add PostgreSQL throttles, reset tokens, and security events.

Revision ID: 0009_auth_security_controls
Revises: 0008_trusted_membership
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_auth_security_controls"
down_revision: str | None = "0008_trusted_membership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
EVENTS = "'login_success','login_failure','logout','session_revoked','all_sessions_revoked','password_changed','password_reset_requested','password_reset_completed','membership_denied','tenant_switch','throttling_triggered'"


def upgrade() -> None:
    op.create_table(
        "throttle_buckets",
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("key_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key_id", sa.SmallInteger(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(key_digest)=32",
            name=op.f("ck_throttle_buckets_key_digest_length"),
        ),
        sa.CheckConstraint(
            "request_count>0", name=op.f("ck_throttle_buckets_request_count_positive")
        ),
        sa.PrimaryKeyConstraint(
            "scope", "key_digest", "window_started_at", name=op.f("pk_throttle_buckets")
        ),
        schema="auth",
    )
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "octet_length(token_digest)=32",
            name=op.f("ck_password_reset_tokens_token_digest_length"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_password_reset_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_tokens")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_password_reset_tokens_digest")),
        schema="auth",
    )
    op.create_index(
        "ix_password_reset_tokens_user_open",
        "password_reset_tokens",
        ["user_id", "consumed_at", "revoked_at"],
        schema="auth",
    )
    op.create_table(
        "security_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(40)),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("session_id", postgresql.UUID(as_uuid=True)),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True)),
        sa.Column("subject_digest", postgresql.BYTEA()),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"event_type IN ({EVENTS})",
            name=op.f("ck_security_events_event_type_allowed"),
        ),
        sa.CheckConstraint(
            "result IN ('success','failure','denied')",
            name=op.f("ck_security_events_result_allowed"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_events")),
        schema="auth",
    )
    op.drop_constraint(
        op.f("ck_sessions_session_revocation_state"),
        "sessions",
        schema="auth",
        type_="check",
    )
    op.create_check_constraint(
        "session_revocation_state",
        "sessions",
        "(revoked_at IS NULL AND revoked_reason IS NULL) OR (revoked_at IS NOT NULL AND revoked_reason IN ('logout','revoke_all','concurrent_limit','password_reset'))",
        schema="auth",
    )
    for table in ("throttle_buckets", "password_reset_tokens", "security_events"):
        op.execute(f"REVOKE ALL ON TABLE auth.{table} FROM PUBLIC")
        op.execute(f"REVOKE ALL ON TABLE auth.{table} FROM sahl_app")
    op.execute("""CREATE FUNCTION auth.consume_throttle(p_scope text,p_key bytea,p_key_id smallint,p_limit integer,p_window_seconds integer)
      RETURNS TABLE(allowed boolean,request_count integer,retry_after_seconds integer)
      LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$
      WITH clock AS (SELECT clock_timestamp() now), bucket AS (
       INSERT INTO auth.throttle_buckets(scope,key_digest,window_started_at,key_id,request_count,expires_at)
       SELECT p_scope,p_key,to_timestamp(floor(extract(epoch from now)/p_window_seconds)*p_window_seconds),p_key_id,1,
              to_timestamp(floor(extract(epoch from now)/p_window_seconds)*p_window_seconds)+make_interval(secs=>p_window_seconds)+interval '48 hours' FROM clock
       ON CONFLICT(scope,key_digest,window_started_at) DO UPDATE SET request_count=auth.throttle_buckets.request_count+1
       RETURNING auth.throttle_buckets.request_count,auth.throttle_buckets.window_started_at)
      SELECT request_count<=p_limit,request_count,
       greatest(1,ceil(extract(epoch from (window_started_at+make_interval(secs=>p_window_seconds)-clock_timestamp())))::integer) FROM bucket $f$""")
    op.execute("""CREATE FUNCTION auth.request_password_reset(p_email text,p_digest bytea,p_token uuid,p_event uuid,p_correlation text)
      RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$
      DECLARE v_user uuid; BEGIN SELECT id INTO v_user FROM auth.users WHERE normalized_email=p_email AND status='active'::auth.user_status;
       IF v_user IS NULL THEN RETURN false; END IF;
       UPDATE auth.password_reset_tokens SET revoked_at=clock_timestamp() WHERE user_id=v_user AND consumed_at IS NULL AND revoked_at IS NULL;
       INSERT INTO auth.password_reset_tokens(id,user_id,token_digest,created_at,expires_at) VALUES(p_token,v_user,p_digest,clock_timestamp(),clock_timestamp()+interval '15 minutes');
       INSERT INTO auth.security_events(id,event_type,result,user_id,correlation_id,created_at) VALUES(p_event,'password_reset_requested','success',v_user,p_correlation,clock_timestamp()); RETURN true; END $f$""")
    op.execute("""CREATE FUNCTION auth.complete_password_reset(p_digest bytea,p_hash text,p_event uuid,p_correlation text)
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
       INSERT INTO auth.security_events(id,event_type,result,user_id,correlation_id,created_at) VALUES(p_event,'password_reset_completed','success',v_token.user_id,p_correlation,clock_timestamp()); RETURN true; END $f$""")
    op.execute("""CREATE FUNCTION auth.record_security_event(p_id uuid,p_type text,p_result text,p_reason text,p_user uuid,p_session uuid,p_membership uuid,p_subject bytea,p_correlation text)
      RETURNS void LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$
      INSERT INTO auth.security_events(id,event_type,result,reason_code,user_id,session_id,membership_id,subject_digest,correlation_id,created_at)
      SELECT p_id,p_type,p_result,p_reason,p_user,
       CASE WHEN EXISTS(SELECT 1 FROM auth.sessions s WHERE s.id=p_session AND (p_user IS NULL OR s.user_id=p_user)) THEN p_session END,
       CASE WHEN EXISTS(SELECT 1 FROM auth.tenant_memberships m WHERE m.id=p_membership AND (p_user IS NULL OR m.user_id=p_user)) THEN p_membership END,
       p_subject,p_correlation,clock_timestamp() $f$""")
    signatures = (
        "auth.consume_throttle(text,bytea,smallint,integer,integer)",
        "auth.request_password_reset(text,bytea,uuid,uuid,text)",
        "auth.complete_password_reset(bytea,text,uuid,text)",
        "auth.record_security_event(uuid,text,text,text,uuid,uuid,uuid,bytea,text)",
    )
    for signature in signatures:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO sahl_migrator")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sahl_app")


def downgrade() -> None:
    for signature in (
        "auth.record_security_event(uuid,text,text,text,uuid,uuid,uuid,bytea,text)",
        "auth.complete_password_reset(bytea,text,uuid,text)",
        "auth.request_password_reset(text,bytea,uuid,uuid,text)",
        "auth.request_password_reset(text,bytea,uuid,text)",
        "auth.consume_throttle(text,bytea,smallint,integer,integer)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.drop_constraint(
        op.f("ck_sessions_session_revocation_state"),
        "sessions",
        schema="auth",
        type_="check",
    )
    op.execute(
        "UPDATE auth.sessions SET revoked_reason='revoke_all' "
        "WHERE revoked_reason='password_reset'"
    )
    op.create_check_constraint(
        "session_revocation_state",
        "sessions",
        "(revoked_at IS NULL AND revoked_reason IS NULL) OR (revoked_at IS NOT NULL AND revoked_reason IN ('logout','revoke_all','concurrent_limit'))",
        schema="auth",
    )
    op.drop_table("security_events", schema="auth")
    op.drop_index(
        "ix_password_reset_tokens_user_open",
        table_name="password_reset_tokens",
        schema="auth",
    )
    op.drop_table("password_reset_tokens", schema="auth")
    op.drop_table("throttle_buckets", schema="auth")
