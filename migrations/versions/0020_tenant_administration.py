# ruff: noqa: E501
"""Add tenant administration, protected bootstrap, and password reset boundaries."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_tenant_administration"
down_revision: str | None = "0019_activity_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_AUDIT_PERMISSIONS = (
    "'platform.tenants.manage','platform.tenants.read','platform.ui_settings.manage',"
    "'tenant.memberships.manage','tenant.memberships.read','tenant.roles.manage',"
    "'tenant.roles.read','tenant.ui_settings.manage','tenant.user_ui_settings.manage_self',"
    "'tenant.workflow_approvals.decide','tenant.workflow_requests.create',"
    "'tenant.workflow_requests.read'"
)
NEW_AUDIT_PERMISSIONS = OLD_AUDIT_PERMISSIONS + (
    ",'tenant.access_audit.read','tenant.dashboard.read','tenant.profile.read',"
    "'tenant.users.invite','tenant.users.manage','tenant.users.read'"
)

TENANT_ADMIN_PERMISSIONS = (
    "tenant.access_audit.read",
    "tenant.dashboard.read",
    "tenant.memberships.manage",
    "tenant.memberships.read",
    "tenant.profile.read",
    "tenant.roles.manage",
    "tenant.roles.read",
    "tenant.ui_settings.manage",
    "tenant.user_ui_settings.manage_self",
    "tenant.users.invite",
    "tenant.users.manage",
    "tenant.users.read",
    "tenant.workflow_approvals.decide",
    "tenant.workflow_requests.create",
    "tenant.workflow_requests.read",
)


def _replace_audit_permissions(previous: str, current: str) -> None:
    escaped_previous = previous.replace("'", "''")
    escaped_current = current.replace("'", "''")
    op.execute(
        f"""
        DO $migration$
        DECLARE definition text;
        BEGIN
            SELECT pg_get_functiondef('auth.validate_security_event_insert()'::regprocedure)
              INTO definition;
            IF strpos(definition, '{escaped_previous}') = 0 THEN
                RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='audit_permission_catalog_mismatch';
            END IF;
            definition := replace(definition, '{escaped_previous}', '{escaped_current}');
            EXECUTE definition;
        END
        $migration$
        """
    )
    op.execute("ALTER FUNCTION auth.validate_security_event_insert() OWNER TO sahl_migrator")
    op.drop_constraint(
        op.f("ck_security_events_permission_catalog"),
        "security_events",
        schema="auth",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_security_events_permission_catalog"),
        "security_events",
        f"permission_id IS NULL OR permission_id IN ({current})",
        schema="auth",
    )


def upgrade() -> None:
    _replace_audit_permissions(OLD_AUDIT_PERMISSIONS, NEW_AUDIT_PERMISSIONS)
    for table in ("roles", "role_permissions", "membership_roles"):
        op.execute(f"ALTER POLICY tenant_isolation ON auth.{table} TO sahl_app,sahl_migrator")
    op.execute("CREATE TYPE auth.role_kind AS ENUM ('custom','tenant_admin')")
    op.add_column(
        "roles",
        sa.Column(
            "kind",
            postgresql.ENUM(name="role_kind", schema="auth", create_type=False),
            server_default="custom",
            nullable=False,
        ),
        schema="auth",
    )
    op.create_index(
        "uq_roles_one_tenant_admin",
        "roles",
        ["tenant_id"],
        unique=True,
        schema="auth",
        postgresql_where=sa.text("kind = 'tenant_admin'::auth.role_kind"),
    )
    op.add_column(
        "password_credentials",
        sa.Column("force_password_change", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="auth",
    )

    op.create_table(
        "tenant_access_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('user_invited','membership_activated','membership_suspended',"
            "'tenant_admin_bootstrapped','password_admin_reset','role_created',"
            "'role_updated','role_disabled','permission_assigned','permission_removed',"
            "'role_assigned','role_removed')",
            name="ck_tenant_access_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["public.tenants.id"],
            ondelete="CASCADE",
            name="fk_tenant_access_events_tenant",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_access_events"),
        schema="app",
    )
    op.create_index(
        "ix_access_events_tenant_created",
        "tenant_access_events",
        ["tenant_id", "created_at", "id"],
        schema="app",
    )
    op.execute("ALTER TABLE app.tenant_access_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app.tenant_access_events FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON app.tenant_access_events "
        "FOR ALL TO sahl_app,sahl_migrator "
        "USING (tenant_id=app.current_tenant_id()) "
        "WITH CHECK (tenant_id=app.current_tenant_id())"
    )
    op.execute("ALTER TABLE app.tenant_access_events OWNER TO sahl_migrator")
    op.execute("REVOKE ALL ON TABLE app.tenant_access_events FROM PUBLIC,sahl_app")
    op.execute("GRANT SELECT,INSERT ON TABLE app.tenant_access_events TO sahl_app")

    op.execute("""
        CREATE FUNCTION auth.tenant_user_directory()
        RETURNS TABLE(
            membership_id uuid,user_id uuid,email text,user_status text,
            membership_status text,membership_version integer,joined_at timestamptz,
            left_at timestamptz,role_ids uuid[],role_keys text[],role_titles text[]
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $f$
          SELECT m.id,u.id,u.email::text,u.status::text,m.status::text,m.version,m.joined_at,m.left_at,
                 COALESCE(array_agg(r.id ORDER BY r.key) FILTER (WHERE r.id IS NOT NULL),ARRAY[]::uuid[]),
                 COALESCE(array_agg(r.key::text ORDER BY r.key) FILTER (WHERE r.id IS NOT NULL),ARRAY[]::text[]),
                 COALESCE(array_agg(r.display_name::text ORDER BY r.key) FILTER (WHERE r.id IS NOT NULL),ARRAY[]::text[])
          FROM auth.tenant_memberships m
          JOIN auth.users u ON u.id=m.user_id
          LEFT JOIN auth.membership_roles mr ON mr.tenant_id=m.tenant_id AND mr.membership_id=m.id
          LEFT JOIN auth.roles r ON r.tenant_id=mr.tenant_id AND r.id=mr.role_id
          WHERE m.tenant_id=app.current_tenant_id()
          GROUP BY m.id,u.id,u.email,u.status,m.status,m.version,m.joined_at,m.left_at
          ORDER BY u.email,m.id
        $f$
    """)
    op.execute("""
        CREATE FUNCTION auth.tenant_role_directory()
        RETURNS TABLE(
            role_id uuid,role_key text,display_name text,status text,kind text,
            version integer,permissions text[]
        ) LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $f$
          SELECT r.id,r.key::text,r.display_name::text,r.status::text,r.kind::text,r.version,
                 COALESCE(array_agg(rp.permission_id::text ORDER BY rp.permission_id)
                   FILTER (WHERE rp.permission_id IS NOT NULL),ARRAY[]::text[])
          FROM auth.roles r
          LEFT JOIN auth.role_permissions rp ON rp.tenant_id=r.tenant_id AND rp.role_id=r.id
          WHERE r.tenant_id=app.current_tenant_id()
          GROUP BY r.id
          ORDER BY r.kind DESC,r.display_name,r.id
        $f$
    """)
    op.execute("""
        CREATE FUNCTION auth.invite_tenant_user(
          p_email text,p_normalized text,p_user uuid,p_membership uuid,p_actor uuid
        ) RETURNS TABLE(membership_id uuid,user_id uuid,membership_status text,membership_version integer)
        LANGUAGE plpgsql VOLATILE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$
        DECLARE v_tenant uuid:=app.current_tenant_id(); v_user uuid; v_member auth.tenant_memberships%ROWTYPE;
        BEGIN
          IF v_tenant IS NULL OR p_email<>btrim(p_email) OR p_normalized<>lower(p_normalized)
             OR length(p_email)>254 OR length(p_normalized)>254 THEN
            RAISE EXCEPTION USING ERRCODE='22023',MESSAGE='tenant_user_invalid';
          END IF;
          PERFORM 1 FROM auth.tenant_memberships m JOIN auth.users u ON u.id=m.user_id
           WHERE m.id=p_actor AND m.tenant_id=v_tenant
             AND m.status='active'::auth.membership_status
             AND u.status='active'::auth.user_status;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='tenant_user_denied';
          END IF;
          PERFORM 1 FROM public.tenants t WHERE t.id=v_tenant AND t.status='active'::public.tenant_status;
          IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23503',MESSAGE='tenant_unavailable'; END IF;
          SELECT u.id INTO v_user FROM auth.users u WHERE u.normalized_email=p_normalized FOR UPDATE;
          IF v_user IS NULL THEN
            v_user:=p_user;
            INSERT INTO auth.users(id,email,normalized_email,status)
            VALUES(v_user,p_email,p_normalized,'pending'::auth.user_status);
          END IF;
          SELECT * INTO v_member FROM auth.tenant_memberships m
           WHERE m.user_id=v_user AND m.tenant_id=v_tenant FOR UPDATE;
          IF NOT FOUND THEN
            INSERT INTO auth.tenant_memberships(id,user_id,tenant_id,status)
            VALUES(p_membership,v_user,v_tenant,'pending'::auth.membership_status)
            RETURNING * INTO v_member;
            INSERT INTO app.tenant_access_events(
              id,tenant_id,actor_membership_id,target_membership_id,event_type
            ) VALUES((lpad(to_hex(floor(extract(epoch FROM clock_timestamp())*1000)::bigint),12,'0')||'7'||substr(replace(gen_random_uuid()::text,'-',''),14))::uuid,
              v_tenant,p_actor,v_member.id,'user_invited');
          END IF;
          RETURN QUERY SELECT v_member.id,v_user,v_member.status::text,v_member.version;
        END $f$
    """)
    op.execute("""
        CREATE FUNCTION auth.set_tenant_membership_status(
          p_membership uuid,p_status text,p_expected integer,p_actor uuid
        ) RETURNS TABLE(membership_id uuid,membership_status text,membership_version integer)
        LANGUAGE plpgsql VOLATILE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$
        DECLARE v_tenant uuid:=app.current_tenant_id(); v_current auth.tenant_memberships%ROWTYPE;
                v_is_admin boolean; v_other_admins integer; v_event text;
        BEGIN
          IF v_tenant IS NULL OR p_status NOT IN ('active','suspended') OR p_membership=p_actor THEN
            RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='membership_change_denied';
          END IF;
          PERFORM 1 FROM auth.tenant_memberships m JOIN auth.users u ON u.id=m.user_id
           WHERE m.id=p_actor AND m.tenant_id=v_tenant
             AND m.status='active'::auth.membership_status
             AND u.status='active'::auth.user_status;
          IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='membership_change_denied';
          END IF;
          SELECT * INTO v_current FROM auth.tenant_memberships m
           WHERE m.id=p_membership AND m.tenant_id=v_tenant FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='P0002',MESSAGE='membership_not_found'; END IF;
          IF v_current.version<>p_expected OR v_current.status='left'::auth.membership_status THEN
            RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='membership_conflict';
          END IF;
          SELECT EXISTS(SELECT 1 FROM auth.membership_roles mr JOIN auth.roles r
            ON r.tenant_id=mr.tenant_id AND r.id=mr.role_id
            WHERE mr.tenant_id=v_tenant AND mr.membership_id=p_membership
              AND r.kind='tenant_admin'::auth.role_kind AND r.status='active'::auth.role_status)
            INTO v_is_admin;
          IF v_is_admin AND p_status<>'active' THEN
            SELECT count(*) INTO v_other_admins FROM auth.membership_roles mr
            JOIN auth.roles r ON r.tenant_id=mr.tenant_id AND r.id=mr.role_id
            JOIN auth.tenant_memberships m ON m.tenant_id=mr.tenant_id AND m.id=mr.membership_id
            WHERE mr.tenant_id=v_tenant AND mr.membership_id<>p_membership
              AND r.kind='tenant_admin'::auth.role_kind AND r.status='active'::auth.role_status
              AND m.status='active'::auth.membership_status;
            IF v_other_admins=0 THEN
              RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='last_tenant_admin';
            END IF;
          END IF;
          UPDATE auth.tenant_memberships SET status=p_status::auth.membership_status,
            joined_at=CASE WHEN p_status='active' THEN COALESCE(joined_at,clock_timestamp()) ELSE joined_at END,
            left_at=NULL,version=version+1,updated_at=clock_timestamp()
            WHERE id=p_membership RETURNING * INTO v_current;
          v_event:=CASE p_status WHEN 'active' THEN 'membership_activated' ELSE 'membership_suspended' END;
          INSERT INTO app.tenant_access_events(id,tenant_id,actor_membership_id,target_membership_id,event_type)
          VALUES((lpad(to_hex(floor(extract(epoch FROM clock_timestamp())*1000)::bigint),12,'0')||'7'||substr(replace(gen_random_uuid()::text,'-',''),14))::uuid,
            v_tenant,p_actor,p_membership,v_event);
          RETURN QUERY SELECT v_current.id,v_current.status::text,v_current.version;
        END $f$
    """)
    op.execute("""
        CREATE FUNCTION auth.bootstrap_tenant_catalog()
        RETURNS TABLE(tenant_id uuid,tenant_name text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $f$
          SELECT t.id,t.name_ar::text FROM public.tenants t
          WHERE pg_has_role(session_user,'sahl_identity_bootstrap','USAGE')
            AND NOT pg_has_role(session_user,'sahl_app','MEMBER')
            AND NOT pg_has_role(session_user,'sahl_migrator','MEMBER')
            AND t.status='active'::public.tenant_status ORDER BY t.name_ar,t.id
        $f$
    """)
    op.execute("""
        CREATE FUNCTION auth.bootstrap_tenant_admin(
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
          VALUES(v_user,p_hash) ON CONFLICT(user_id) DO NOTHING;
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
    """)
    op.execute("""
        CREATE FUNCTION auth.admin_password_snapshot(p_email text)
        RETURNS TABLE(user_id uuid,credential_version bigint,security_version bigint)
        LANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$
          SELECT u.id,c.credential_version::bigint,u.security_version::bigint
          FROM auth.users u JOIN auth.password_credentials c ON c.user_id=u.id
          WHERE pg_has_role(session_user,'sahl_identity_bootstrap','USAGE')
            AND NOT pg_has_role(session_user,'sahl_app','MEMBER')
            AND NOT pg_has_role(session_user,'sahl_migrator','MEMBER')
            AND u.normalized_email=p_email
        $f$
    """)
    op.execute("""
        CREATE FUNCTION auth.admin_apply_password_reset(
          p_user uuid,p_credential bigint,p_security bigint,p_hash text,p_force boolean
        ) RETURNS bigint LANGUAGE plpgsql VOLATILE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$
        DECLARE v_revoked bigint; v_event uuid; v_correlation uuid:=gen_random_uuid();
        BEGIN
          IF NOT pg_has_role(session_user,'sahl_identity_bootstrap','USAGE')
             OR pg_has_role(session_user,'sahl_app','MEMBER')
             OR pg_has_role(session_user,'sahl_migrator','MEMBER')
             OR p_hash NOT LIKE '$argon2id$%' THEN
            RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='identity_bootstrap_denied';
          END IF;
          PERFORM 1 FROM auth.users u WHERE u.id=p_user AND u.security_version=p_security FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='identity_conflict'; END IF;
          UPDATE auth.password_credentials SET password_hash=p_hash,
            credential_version=credential_version+1,changed_at=clock_timestamp(),
            force_password_change=p_force
            WHERE user_id=p_user AND credential_version=p_credential;
          IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='40001',MESSAGE='identity_conflict'; END IF;
          UPDATE auth.users SET security_version=security_version+1,status='active'::auth.user_status,
            updated_at=clock_timestamp() WHERE id=p_user;
          UPDATE auth.sessions SET revoked_at=clock_timestamp(),revoked_reason='password_reset'
            WHERE user_id=p_user AND revoked_at IS NULL;
          GET DIAGNOSTICS v_revoked=ROW_COUNT;
          v_event:=(lpad(to_hex(floor(extract(epoch FROM clock_timestamp())*1000)::bigint),12,'0')||'7'||substr(replace(gen_random_uuid()::text,'-',''),14))::uuid;
          PERFORM auth.append_security_event(v_event,'password_reset_completed','success',
            'password_reset',p_user,NULL,NULL,NULL,v_correlation,NULL,NULL,NULL,NULL,NULL,NULL);
          IF v_revoked>0 THEN
            PERFORM auth.append_security_event((lpad(to_hex(floor(extract(epoch FROM clock_timestamp())*1000)::bigint),12,'0')||'7'||substr(replace(gen_random_uuid()::text,'-',''),14))::uuid,'all_sessions_revoked','success',
              'password_reset',p_user,NULL,NULL,NULL,v_correlation,NULL,NULL,NULL,NULL,NULL,NULL);
          END IF;
          RETURN v_revoked;
        END $f$
    """)

    op.execute("""
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
          UPDATE auth.password_credentials SET password_hash=p_new_hash,
            credential_version=credential_version+1,changed_at=clock_timestamp(),force_password_change=false
            WHERE user_id=v_user;
          UPDATE auth.users SET security_version=security_version+1,updated_at=clock_timestamp() WHERE id=v_user;
          UPDATE auth.sessions SET revoked_at=clock_timestamp(),revoked_reason='revoke_all'
           WHERE user_id=v_user AND revoked_at IS NULL;
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
    """)
    op.execute("DROP FUNCTION auth.session_identity(bytea)")
    op.execute("""
        CREATE FUNCTION auth.session_identity(p_bearer_digest bytea)
        RETURNS TABLE(user_id uuid,email text,security_version integer,force_password_change boolean)
        LANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$
          SELECT u.id,u.email::text,u.security_version,c.force_password_change
          FROM auth.sessions s JOIN auth.users u ON u.id=s.user_id
          JOIN auth.password_credentials c ON c.user_id=u.id
          WHERE s.bearer_digest=p_bearer_digest AND s.revoked_at IS NULL
            AND s.idle_expires_at>statement_timestamp() AND s.absolute_expires_at>statement_timestamp()
            AND u.status='active'::auth.user_status AND u.security_version=s.security_version
        $f$
    """)

    runtime = (
        "auth.tenant_user_directory()",
        "auth.tenant_role_directory()",
        "auth.invite_tenant_user(text,text,uuid,uuid,uuid)",
        "auth.set_tenant_membership_status(uuid,text,integer,uuid)",
        "auth.session_identity(bytea)",
    )
    bootstrap = (
        "auth.bootstrap_tenant_catalog()",
        "auth.bootstrap_tenant_admin(uuid,text,text,text,uuid,uuid,uuid)",
        "auth.admin_password_snapshot(text)",
        "auth.admin_apply_password_reset(uuid,bigint,bigint,text,boolean)",
    )
    for signature in (
        *runtime,
        *bootstrap,
        "auth.apply_password_change(bytea,bigint,bigint,text,text)",
    ):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO sahl_migrator")
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,sahl_app,sahl_identity_bootstrap"
        )
    for signature in runtime:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sahl_app")
    for signature in bootstrap:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sahl_identity_bootstrap")
    op.execute("GRANT USAGE ON SCHEMA auth TO sahl_identity_bootstrap")
    op.execute(
        "GRANT EXECUTE ON FUNCTION auth.apply_password_change(bytea,bigint,bigint,text,text) TO sahl_app"
    )


def downgrade() -> None:
    op.execute("REVOKE USAGE ON SCHEMA auth FROM sahl_identity_bootstrap")
    op.execute("""
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
          UPDATE auth.password_credentials SET password_hash=p_new_hash,
            credential_version=credential_version+1,changed_at=clock_timestamp() WHERE user_id=v_user;
          UPDATE auth.users SET security_version=security_version+1,updated_at=clock_timestamp() WHERE id=v_user;
          UPDATE auth.sessions SET revoked_at=clock_timestamp(),revoked_reason='revoke_all'
           WHERE user_id=v_user AND revoked_at IS NULL;
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
    """)
    op.execute("DROP FUNCTION auth.session_identity(bytea)")
    op.execute("""
        CREATE FUNCTION auth.session_identity(p_bearer_digest bytea)
        RETURNS TABLE(user_id uuid,email text,security_version integer)
        LANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$
          SELECT u.id,u.email::text,u.security_version FROM auth.sessions s
          JOIN auth.users u ON u.id=s.user_id WHERE s.bearer_digest=p_bearer_digest
            AND s.revoked_at IS NULL AND s.idle_expires_at>statement_timestamp()
            AND s.absolute_expires_at>statement_timestamp()
            AND u.status='active'::auth.user_status AND u.security_version=s.security_version
        $f$
    """)
    op.execute("ALTER FUNCTION auth.session_identity(bytea) OWNER TO sahl_migrator")
    op.execute("REVOKE ALL ON FUNCTION auth.session_identity(bytea) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth.session_identity(bytea) TO sahl_app")
    for signature in (
        "auth.bootstrap_tenant_admin(uuid,text,text,text,uuid,uuid,uuid)",
        "auth.bootstrap_tenant_catalog()",
        "auth.admin_password_snapshot(text)",
        "auth.admin_apply_password_reset(uuid,bigint,bigint,text,boolean)",
        "auth.set_tenant_membership_status(uuid,text,integer,uuid)",
        "auth.invite_tenant_user(text,text,uuid,uuid,uuid)",
        "auth.tenant_role_directory()",
        "auth.tenant_user_directory()",
    ):
        op.execute(f"DROP FUNCTION {signature}")
    op.drop_table("tenant_access_events", schema="app")
    op.drop_column("password_credentials", "force_password_change", schema="auth")
    op.drop_index("uq_roles_one_tenant_admin", table_name="roles", schema="auth")
    op.drop_column("roles", "kind", schema="auth")
    op.execute("DROP TYPE auth.role_kind")
    for table in ("roles", "role_permissions", "membership_roles"):
        op.execute(f"ALTER POLICY tenant_isolation ON auth.{table} TO sahl_app")
    _replace_audit_permissions(NEW_AUDIT_PERMISSIONS, OLD_AUDIT_PERMISSIONS)
