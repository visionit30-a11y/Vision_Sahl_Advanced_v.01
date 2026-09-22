"""Disambiguate the tenant administrator bootstrap credential upsert.

Revision ID: 0021_tenant_admin_bootstrap_fix
Revises: 0020_tenant_administration
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_tenant_admin_bootstrap_fix"
down_revision: str | None = "0020_tenant_administration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _function_sql(*, credential_conflict: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION auth.bootstrap_tenant_admin(
          p_tenant uuid,p_email text,p_normalized text,p_hash text,p_user uuid,p_membership uuid,p_role uuid
        ) RETURNS TABLE(user_id uuid,membership_id uuid,role_id uuid)
        LANGUAGE plpgsql VOLATILE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$
        DECLARE v_user uuid; v_member uuid; v_role uuid;
        BEGIN
          IF NOT pg_has_role(session_user,'sahl_identity_bootstrap','USAGE')
             OR pg_has_role(session_user,'sahl_app','MEMBER')
             OR pg_has_role(session_user,'sahl_migrator','MEMBER')
             OR p_hash NOT LIKE '$argon2id$%'
             OR p_email<>btrim(p_email) OR p_normalized<>lower(p_normalized)
             OR length(p_email)>254 OR length(p_normalized)>254 THEN
            RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='identity_bootstrap_denied';
          END IF;
          PERFORM 1 FROM public.tenants t WHERE t.id=p_tenant AND t.status='active'::public.tenant_status;
          IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23503',MESSAGE='tenant_unavailable'; END IF;
          PERFORM set_config('app.tenant_id',p_tenant::text,true);
          SELECT u.id INTO v_user FROM auth.users u WHERE u.normalized_email=p_normalized FOR UPDATE;
          IF v_user IS NULL THEN
            v_user:=p_user;
            INSERT INTO auth.users(id,email,normalized_email,status,email_verified_at)
            VALUES(v_user,p_email,p_normalized,'active'::auth.user_status,clock_timestamp());
          ELSE
            UPDATE auth.users SET status='active'::auth.user_status,updated_at=clock_timestamp()
             WHERE id=v_user AND status<>'active'::auth.user_status;
          END IF;
          INSERT INTO auth.password_credentials(user_id,password_hash)
          VALUES(v_user,p_hash) {credential_conflict};
          SELECT m.id INTO v_member FROM auth.tenant_memberships m
           WHERE m.user_id=v_user AND m.tenant_id=p_tenant FOR UPDATE;
          IF v_member IS NULL THEN
            v_member:=p_membership;
            INSERT INTO auth.tenant_memberships(id,user_id,tenant_id,status,joined_at)
            VALUES(v_member,v_user,p_tenant,'active'::auth.membership_status,clock_timestamp());
          ELSE
            UPDATE auth.tenant_memberships SET status='active'::auth.membership_status,
              joined_at=COALESCE(joined_at,clock_timestamp()),left_at=NULL,version=version+1,
              updated_at=clock_timestamp() WHERE id=v_member
              AND (status<>'active'::auth.membership_status OR joined_at IS NULL OR left_at IS NOT NULL);
          END IF;
          SELECT r.id INTO v_role FROM auth.roles r
           WHERE r.tenant_id=p_tenant AND r.kind='tenant_admin'::auth.role_kind FOR UPDATE;
          IF v_role IS NULL THEN
            v_role:=p_role;
            INSERT INTO auth.roles(id,tenant_id,key,display_name,kind)
            VALUES(v_role,p_tenant,'tenant_admin','Tenant Admin / مسؤول الجمعية',
              'tenant_admin'::auth.role_kind);
          ELSE
            UPDATE auth.roles SET status='active'::auth.role_status,
              updated_at=clock_timestamp(),version=version+1
              WHERE id=v_role AND status<>'active'::auth.role_status;
          END IF;
          INSERT INTO auth.role_permissions(tenant_id,role_id,permission_id)
          SELECT p_tenant,v_role,permission FROM unnest(ARRAY[
            'tenant.access_audit.read','tenant.dashboard.read','tenant.memberships.manage',
            'tenant.memberships.read','tenant.profile.read','tenant.roles.manage',
            'tenant.roles.read','tenant.ui_settings.manage','tenant.user_ui_settings.manage_self',
            'tenant.users.invite','tenant.users.manage','tenant.users.read',
            'tenant.workflow_approvals.decide','tenant.workflow_requests.create',
            'tenant.workflow_requests.read'
          ]::text[]) AS permission ON CONFLICT DO NOTHING;
          INSERT INTO auth.membership_roles(tenant_id,membership_id,role_id)
          VALUES(p_tenant,v_member,v_role) ON CONFLICT DO NOTHING;
          IF NOT EXISTS(SELECT 1 FROM app.tenant_access_events e WHERE e.tenant_id=p_tenant
            AND e.target_membership_id=v_member AND e.event_type='tenant_admin_bootstrapped') THEN
            INSERT INTO app.tenant_access_events(id,tenant_id,target_membership_id,role_id,event_type)
            VALUES((lpad(to_hex(floor(extract(epoch FROM clock_timestamp())*1000)::bigint),12,'0')||'7'||substr(replace(gen_random_uuid()::text,'-',''),14))::uuid,
              p_tenant,v_member,v_role,'tenant_admin_bootstrapped');
          END IF;
          RETURN QUERY SELECT v_user,v_member,v_role;
        END $f$
    """


def _secure_function() -> None:
    signature = "auth.bootstrap_tenant_admin(uuid,text,text,text,uuid,uuid,uuid)"
    op.execute(f"ALTER FUNCTION {signature} OWNER TO sahl_migrator")
    op.execute(
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,sahl_app,sahl_identity_bootstrap"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sahl_identity_bootstrap")


def upgrade() -> None:
    op.execute(
        _function_sql(
            credential_conflict="ON CONFLICT ON CONSTRAINT pk_password_credentials DO NOTHING"
        )
    )
    _secure_function()


def downgrade() -> None:
    op.execute(_function_sql(credential_conflict="ON CONFLICT(user_id) DO NOTHING"))
    _secure_function()
