"""Qualify password change columns that collide with table-return variables.

Revision ID: 0022_password_change_fix
Revises: 0021_tenant_admin_bootstrap_fix
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022_password_change_fix"
down_revision: str | None = "0021_tenant_admin_bootstrap_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _function_sql(*, qualify_columns: bool) -> str:
    credential_version = (
        "c.credential_version+1" if qualify_columns else "credential_version+1"
    )
    credential_user = "c.user_id" if qualify_columns else "user_id"
    user_security_version = (
        "u.security_version+1" if qualify_columns else "security_version+1"
    )
    session_user = "s.user_id" if qualify_columns else "user_id"
    return f"""
        CREATE OR REPLACE FUNCTION auth.apply_password_change(
          p_digest bytea,p_credential bigint,p_security bigint,p_old_hash text,p_new_hash text
        ) RETURNS TABLE(user_id uuid,revoked_sessions bigint)
        LANGUAGE plpgsql VOLATILE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$
        DECLARE v_user uuid; v_count bigint; v_event uuid; v_correlation uuid:=gen_random_uuid();
        BEGIN
          SELECT s.user_id INTO v_user FROM auth.sessions s WHERE s.bearer_digest=p_digest;
          IF v_user IS NULL OR NOT auth.confirm_password_authentication(v_user,p_credential,p_security,p_old_hash) THEN RETURN; END IF;
          PERFORM 1 FROM auth.sessions s WHERE s.bearer_digest=p_digest AND s.user_id=v_user
           AND s.revoked_at IS NULL AND s.idle_expires_at>clock_timestamp()
           AND s.absolute_expires_at>clock_timestamp() AND s.security_version=p_security FOR UPDATE;
          IF NOT FOUND THEN RETURN; END IF;
          UPDATE auth.password_credentials AS c SET password_hash=p_new_hash,
            credential_version={credential_version},changed_at=clock_timestamp(),force_password_change=false
            WHERE {credential_user}=v_user;
          UPDATE auth.users AS u SET security_version={user_security_version},updated_at=clock_timestamp()
            WHERE u.id=v_user;
          UPDATE auth.sessions AS s SET revoked_at=clock_timestamp(),revoked_reason='revoke_all'
           WHERE {session_user}=v_user AND s.revoked_at IS NULL;
          GET DIAGNOSTICS v_count=ROW_COUNT;
          v_event:=(lpad(to_hex(floor(extract(epoch FROM clock_timestamp())*1000)::bigint),12,'0')||'7'||substr(replace(gen_random_uuid()::text,'-',''),14))::uuid;
          PERFORM auth.append_security_event(v_event,'password_changed','success',NULL,
            v_user,NULL,NULL,NULL,v_correlation,NULL,NULL,NULL,NULL,NULL,NULL);
          IF v_count>0 THEN
            PERFORM auth.append_security_event((lpad(to_hex(floor(extract(epoch FROM clock_timestamp())*1000)::bigint),12,'0')||'7'||substr(replace(gen_random_uuid()::text,'-',''),14))::uuid,'all_sessions_revoked','success','revoke_all',
              v_user,NULL,NULL,NULL,v_correlation,NULL,NULL,NULL,NULL,NULL,NULL);
          END IF;
          RETURN QUERY SELECT v_user,v_count;
        END $f$
    """


def _secure_function() -> None:
    signature = "auth.apply_password_change(bytea,bigint,bigint,text,text)"
    op.execute(f"ALTER FUNCTION {signature} OWNER TO sahl_migrator")
    op.execute(
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,sahl_app,sahl_identity_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sahl_app")


def upgrade() -> None:
    op.execute(_function_sql(qualify_columns=True))
    _secure_function()


def downgrade() -> None:
    op.execute(_function_sql(qualify_columns=False))
    _secure_function()
