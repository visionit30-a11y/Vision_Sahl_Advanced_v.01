# ruff: noqa: E501
"""Attest role changes under existing RLS, and wire mandatory reset events.

The private intent is transaction-bound and must be consumed before commit.
RBAC triggers inspect actual OLD/NEW tuples, never SELECT protected role rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_security_event_wiring"
down_revision: str | None = "0014_security_audit_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREPARE = "auth.prepare_role_security_event(uuid,text,uuid,uuid,uuid,uuid,uuid,text,uuid,integer)"
CANCEL = "auth.cancel_role_security_event(uuid)"
ATTEST = "auth.attest_role_security_change()"
EMPTY = "auth.require_consumed_role_security_event()"

PREVIOUS_VALIDATOR = "        CREATE OR REPLACE FUNCTION auth.validate_security_event_insert()\n        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog\n        AS $function$\n        DECLARE\n            v_valid boolean;\n            v_session_user uuid;\n            v_selected_membership uuid;\n            v_membership_user uuid;\n        BEGIN\n            IF NEW.event_type IN ('role_created','role_updated','role_disabled','role_permission_assigned','role_permission_removed','membership_role_assigned','membership_role_removed','security_events_pruned') THEN\n                RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n            END IF;\n            SELECT (event_type IN ('all_sessions_revoked','authorization_denied','csrf_rejected','login_failure','login_success','logout','membership_denied','membership_role_assigned','membership_role_removed','origin_rejected','password_changed','password_reset_completed','password_reset_requested','role_created','role_disabled','role_permission_assigned','role_permission_removed','role_updated','security_events_pruned','session_revoked','tenant_switch','throttling_triggered')) AND (result IN ('success','failure','denied')) AND ((event_type = 'login_success' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'login_failure' AND result = 'failure' AND (reason_code IS NULL OR reason_code IN ('dependency_unavailable','invalid_credentials'))) OR (event_type = 'logout' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('logout'))) OR (event_type = 'session_revoked' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('concurrent_limit','logout','password_reset','revoke_all'))) OR (event_type = 'all_sessions_revoked' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('password_reset','revoke_all'))) OR (event_type = 'password_changed' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('password_reset'))) OR (event_type = 'password_reset_requested' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'password_reset_completed' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('password_reset'))) OR (event_type = 'membership_denied' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('dependency_unavailable','membership_unavailable'))) OR (event_type = 'tenant_switch' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'throttling_triggered' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('csrf_bootstrap','login_ip','login_ip_username','login_username','reset_ip','reset_username'))) OR (event_type = 'authorization_denied' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('dependency_unavailable','membership_unavailable','permission_denied'))) OR (event_type = 'csrf_rejected' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('csrf_invalid','csrf_missing','csrf_stale'))) OR (event_type = 'origin_rejected' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('origin_denied'))) OR (event_type = 'role_created' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'role_updated' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'role_disabled' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'role_permission_assigned' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'role_permission_removed' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'membership_role_assigned' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'membership_role_removed' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'security_events_pruned' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('retention_expired')))) AND (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') AND (correlation_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') AND ((user_id IS NOT NULL OR (session_id IS NULL AND membership_id IS NULL)) AND (event_type NOT IN ('tenant_switch','membership_role_assigned','membership_role_removed','role_created','role_disabled','role_permission_assigned','role_permission_removed','role_updated') OR (user_id IS NOT NULL AND session_id IS NOT NULL AND membership_id IS NOT NULL))) AND ((event_type IN ('membership_role_assigned','membership_role_removed','role_created','role_disabled','role_permission_assigned','role_permission_removed','role_updated')) = (role_id IS NOT NULL)) AND ((event_type IN ('membership_role_assigned','membership_role_removed')) = (target_membership_id IS NOT NULL)) AND (permission_id IS NULL OR permission_id IN ('platform.tenants.manage','platform.tenants.read','platform.ui_settings.manage','tenant.memberships.manage','tenant.memberships.read','tenant.roles.manage','tenant.roles.read','tenant.ui_settings.manage','tenant.user_ui_settings.manage_self')) AND ((event_type NOT IN ('role_permission_assigned','role_permission_removed') OR permission_id IS NOT NULL) AND (permission_id IS NULL OR event_type IN ('authorization_denied','role_permission_assigned','role_permission_removed'))) AND ((subject_digest IS NULL AND subject_kind IS NULL AND subject_key_id IS NULL) OR (subject_digest IS NOT NULL AND octet_length(subject_digest) = 32 AND subject_kind IS NOT NULL AND subject_kind IN ('login_ip','login_username','reset_ip','reset_username') AND subject_key_id IS NOT NULL AND subject_key_id BETWEEN 1 AND 32767)) AND ((event_type <> 'security_events_pruned' AND affected_count IS NULL) OR (event_type = 'security_events_pruned' AND affected_count IS NOT NULL AND affected_count >= 0 AND user_id IS NULL AND session_id IS NULL AND membership_id IS NULL AND role_id IS NULL AND target_membership_id IS NULL AND subject_digest IS NULL AND subject_kind IS NULL AND subject_key_id IS NULL)) INTO v_valid FROM (SELECT NEW.*) AS event_record;\n            IF v_valid IS DISTINCT FROM TRUE THEN\n                RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n            END IF;\n            IF NEW.user_id IS NOT NULL THEN\n                PERFORM 1 FROM auth.users WHERE id = NEW.user_id FOR KEY SHARE;\n                IF NOT FOUND THEN\n                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n                END IF;\n            END IF;\n            IF NEW.session_id IS NOT NULL THEN\n                SELECT user_id, selected_membership_id INTO v_session_user, v_selected_membership\n                FROM auth.sessions WHERE id = NEW.session_id FOR SHARE;\n                IF NOT FOUND OR v_session_user IS DISTINCT FROM NEW.user_id THEN\n                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n                END IF;\n                IF NEW.membership_id IS NOT NULL AND v_selected_membership IS DISTINCT FROM NEW.membership_id THEN\n                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n                END IF;\n            END IF;\n            IF NEW.membership_id IS NOT NULL THEN\n                SELECT user_id INTO v_membership_user\n                FROM auth.tenant_memberships WHERE id = NEW.membership_id FOR KEY SHARE;\n                IF NOT FOUND OR v_membership_user IS DISTINCT FROM NEW.user_id THEN\n                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n                END IF;\n            END IF;\n            NEW.created_at := clock_timestamp();\n            RETURN NEW;\n        END\n        $function$;\n"
VALIDATOR = "        CREATE OR REPLACE FUNCTION auth.validate_security_event_insert()\n        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog\n        AS $function$\n        DECLARE\n            v_valid boolean;\n            v_session_user uuid;\n            v_selected_membership uuid;\n            v_membership_user uuid;\n        BEGIN\n            IF NEW.event_type = 'security_events_pruned' THEN\n                RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n            END IF;\n            SELECT (event_type IN ('all_sessions_revoked','authorization_denied','csrf_rejected','login_failure','login_success','logout','membership_denied','membership_role_assigned','membership_role_removed','origin_rejected','password_changed','password_reset_completed','password_reset_requested','role_created','role_disabled','role_permission_assigned','role_permission_removed','role_updated','security_events_pruned','session_revoked','tenant_switch','throttling_triggered')) AND (result IN ('success','failure','denied')) AND ((event_type = 'login_success' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'login_failure' AND result = 'failure' AND (reason_code IS NULL OR reason_code IN ('dependency_unavailable','invalid_credentials'))) OR (event_type = 'logout' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('logout'))) OR (event_type = 'session_revoked' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('concurrent_limit','logout','password_reset','revoke_all'))) OR (event_type = 'all_sessions_revoked' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('password_reset','revoke_all'))) OR (event_type = 'password_changed' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('password_reset'))) OR (event_type = 'password_reset_requested' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'password_reset_completed' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('password_reset'))) OR (event_type = 'membership_denied' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('dependency_unavailable','membership_unavailable'))) OR (event_type = 'tenant_switch' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'throttling_triggered' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('csrf_bootstrap','login_ip','login_ip_username','login_username','reset_ip','reset_username'))) OR (event_type = 'authorization_denied' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('dependency_unavailable','membership_unavailable','permission_denied'))) OR (event_type = 'csrf_rejected' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('csrf_invalid','csrf_missing','csrf_stale'))) OR (event_type = 'origin_rejected' AND result = 'denied' AND (reason_code IS NULL OR reason_code IN ('origin_denied'))) OR (event_type = 'role_created' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'role_updated' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'role_disabled' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'role_permission_assigned' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'role_permission_removed' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'membership_role_assigned' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'membership_role_removed' AND result = 'success' AND reason_code IS NULL) OR (event_type = 'security_events_pruned' AND result = 'success' AND (reason_code IS NULL OR reason_code IN ('retention_expired')))) AND (id::text ~ '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') AND (correlation_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$') AND ((user_id IS NOT NULL OR (session_id IS NULL AND membership_id IS NULL)) AND (event_type NOT IN ('tenant_switch','membership_role_assigned','membership_role_removed','role_created','role_disabled','role_permission_assigned','role_permission_removed','role_updated') OR (user_id IS NOT NULL AND session_id IS NOT NULL AND membership_id IS NOT NULL))) AND ((event_type IN ('membership_role_assigned','membership_role_removed','role_created','role_disabled','role_permission_assigned','role_permission_removed','role_updated')) = (role_id IS NOT NULL)) AND ((event_type IN ('membership_role_assigned','membership_role_removed')) = (target_membership_id IS NOT NULL)) AND (permission_id IS NULL OR permission_id IN ('platform.tenants.manage','platform.tenants.read','platform.ui_settings.manage','tenant.memberships.manage','tenant.memberships.read','tenant.roles.manage','tenant.roles.read','tenant.ui_settings.manage','tenant.user_ui_settings.manage_self')) AND ((event_type NOT IN ('role_permission_assigned','role_permission_removed') OR permission_id IS NOT NULL) AND (permission_id IS NULL OR event_type IN ('authorization_denied','role_permission_assigned','role_permission_removed'))) AND ((subject_digest IS NULL AND subject_kind IS NULL AND subject_key_id IS NULL) OR (subject_digest IS NOT NULL AND octet_length(subject_digest) = 32 AND subject_kind IS NOT NULL AND subject_kind IN ('login_ip','login_username','reset_ip','reset_username') AND subject_key_id IS NOT NULL AND subject_key_id BETWEEN 1 AND 32767)) AND ((event_type <> 'security_events_pruned' AND affected_count IS NULL) OR (event_type = 'security_events_pruned' AND affected_count IS NOT NULL AND affected_count >= 0 AND user_id IS NULL AND session_id IS NULL AND membership_id IS NULL AND role_id IS NULL AND target_membership_id IS NULL AND subject_digest IS NULL AND subject_kind IS NULL AND subject_key_id IS NULL)) INTO v_valid FROM (SELECT NEW.*) AS event_record;\n            IF v_valid IS DISTINCT FROM TRUE THEN\n                RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n            END IF;\n            IF NEW.role_id IS NOT NULL THEN\n                DELETE FROM auth.role_security_event_intents\n                WHERE transaction_id=txid_current() AND backend_pid=pg_backend_pid()\n                  AND event_id=NEW.id AND event_type=NEW.event_type AND attested\n                  AND user_id=NEW.user_id AND session_id=NEW.session_id\n                  AND membership_id=NEW.membership_id AND role_id=NEW.role_id\n                  AND target_membership_id IS NOT DISTINCT FROM NEW.target_membership_id\n                  AND permission_id IS NOT DISTINCT FROM NEW.permission_id\n                  AND correlation_id::text=NEW.correlation_id\n                  AND tenant_id=app.current_tenant_id();\n                IF NOT FOUND THEN\n                    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='audit_event_invalid';\n                END IF;\n            END IF;\n            IF NEW.user_id IS NOT NULL THEN\n                PERFORM 1 FROM auth.users WHERE id = NEW.user_id FOR KEY SHARE;\n                IF NOT FOUND THEN\n                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n                END IF;\n            END IF;\n            IF NEW.session_id IS NOT NULL THEN\n                SELECT user_id, selected_membership_id INTO v_session_user, v_selected_membership\n                FROM auth.sessions WHERE id = NEW.session_id FOR SHARE;\n                IF NOT FOUND OR v_session_user IS DISTINCT FROM NEW.user_id THEN\n                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n                END IF;\n                IF NEW.membership_id IS NOT NULL AND v_selected_membership IS DISTINCT FROM NEW.membership_id THEN\n                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n                END IF;\n            END IF;\n            IF NEW.membership_id IS NOT NULL THEN\n                SELECT user_id INTO v_membership_user\n                FROM auth.tenant_memberships WHERE id = NEW.membership_id FOR KEY SHARE;\n                IF NOT FOUND OR v_membership_user IS DISTINCT FROM NEW.user_id THEN\n                    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'audit_event_invalid';\n                END IF;\n            END IF;\n            NEW.created_at := clock_timestamp();\n            RETURN NEW;\n        END\n        $function$;\n"


PREPARE_SQL = """
CREATE FUNCTION auth.prepare_role_security_event(
 p_event uuid,p_type text,p_user uuid,p_session uuid,p_membership uuid,
 p_role uuid,p_target uuid,p_permission text,p_correlation uuid,p_membership_version integer
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $f$
DECLARE v_tenant uuid;
BEGIN
 IF p_type NOT IN ('role_created','role_updated','role_disabled','role_permission_assigned',
   'role_permission_removed','membership_role_assigned','membership_role_removed')
   OR p_event IS NULL OR p_role IS NULL OR p_correlation IS NULL
   OR (p_type IN ('role_permission_assigned','role_permission_removed')) <> (p_permission IS NOT NULL)
   OR (p_type IN ('membership_role_assigned','membership_role_removed')) <> (p_target IS NOT NULL)
 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='audit_event_invalid'; END IF;
 -- Match credential mutation lock ordering before acquiring a session lock.
 PERFORM 1 FROM auth.users WHERE id=p_user FOR SHARE;
 SELECT m.tenant_id INTO v_tenant
 FROM auth.sessions s JOIN auth.users u ON u.id=s.user_id
 JOIN auth.tenant_memberships m ON m.id=s.selected_membership_id AND m.user_id=u.id
 JOIN public.tenants t ON t.id=m.tenant_id
 WHERE s.id=p_session AND s.user_id=p_user AND m.id=p_membership
   AND s.revoked_at IS NULL AND s.idle_expires_at>clock_timestamp()
   AND s.absolute_expires_at>clock_timestamp() AND s.security_version=u.security_version
   AND s.selected_membership_version=m.version AND m.version=p_membership_version
   AND m.status='active'::auth.membership_status AND u.status='active'::auth.user_status
   AND t.status='active'::public.tenant_status AND m.tenant_id=app.current_tenant_id()
 FOR SHARE OF s,u,m,t;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='audit_event_invalid'; END IF;
 IF p_target IS NOT NULL THEN
   PERFORM 1 FROM auth.tenant_memberships WHERE id=p_target AND tenant_id=v_tenant
     AND status='active'::auth.membership_status FOR SHARE;
   IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='audit_event_invalid'; END IF;
 END IF;
 INSERT INTO auth.role_security_event_intents(
   transaction_id,backend_pid,event_id,event_type,user_id,session_id,membership_id,
   tenant_id,role_id,target_membership_id,permission_id,correlation_id,attested)
 VALUES(txid_current(),pg_backend_pid(),p_event,p_type,p_user,p_session,p_membership,
   v_tenant,p_role,p_target,p_permission,p_correlation,false);
END $f$;
"""

ATTEST_SQL = """
CREATE FUNCTION auth.attest_role_security_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $f$
DECLARE v_intent auth.role_security_event_intents%ROWTYPE;
 v_type text; v_role uuid; v_tenant uuid; v_member uuid; v_permission text;
BEGIN
 SELECT * INTO v_intent FROM auth.role_security_event_intents
 WHERE transaction_id=txid_current() AND backend_pid=pg_backend_pid() FOR UPDATE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF TG_TABLE_SCHEMA <> 'auth' THEN
   RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='audit_event_invalid';
 END IF;
 IF TG_TABLE_NAME='roles' THEN
   IF TG_OP='INSERT' THEN
     v_type:='role_created'; v_role:=NEW.id; v_tenant:=NEW.tenant_id;
   ELSIF TG_OP='UPDATE' AND NEW.id=OLD.id AND NEW.tenant_id=OLD.tenant_id
     AND NEW.key=OLD.key AND NEW.version=OLD.version+1 THEN
     v_role:=NEW.id; v_tenant:=NEW.tenant_id;
     IF OLD.status='active'::auth.role_status AND NEW.status='inactive'::auth.role_status THEN
       v_type:='role_disabled';
     ELSIF NEW.status=OLD.status THEN v_type:='role_updated'; END IF;
   END IF;
 ELSIF TG_TABLE_NAME='role_permissions' THEN
   IF TG_OP='INSERT' THEN
     v_type:='role_permission_assigned'; v_role:=NEW.role_id;
     v_tenant:=NEW.tenant_id; v_permission:=NEW.permission_id;
   ELSIF TG_OP='DELETE' THEN
     v_type:='role_permission_removed'; v_role:=OLD.role_id;
     v_tenant:=OLD.tenant_id; v_permission:=OLD.permission_id;
   END IF;
 ELSIF TG_TABLE_NAME='membership_roles' THEN
   IF TG_OP='INSERT' THEN
     v_type:='membership_role_assigned'; v_role:=NEW.role_id;
     v_tenant:=NEW.tenant_id; v_member:=NEW.membership_id;
   ELSIF TG_OP='DELETE' THEN
     v_type:='membership_role_removed'; v_role:=OLD.role_id;
     v_tenant:=OLD.tenant_id; v_member:=OLD.membership_id;
   END IF;
 END IF;
 IF v_type IS NULL OR v_intent.attested OR v_intent.event_type IS DISTINCT FROM v_type
   OR v_intent.role_id IS DISTINCT FROM v_role OR v_intent.tenant_id IS DISTINCT FROM v_tenant
   OR v_intent.target_membership_id IS DISTINCT FROM v_member
   OR v_intent.permission_id IS DISTINCT FROM v_permission THEN
   RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='audit_event_invalid';
 END IF;
 UPDATE auth.role_security_event_intents SET attested=true
 WHERE transaction_id=v_intent.transaction_id;
 RETURN NULL;
END $f$;
"""

CANCEL_SQL = """
CREATE FUNCTION auth.cancel_role_security_event(p_event uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $f$
BEGIN
 DELETE FROM auth.role_security_event_intents WHERE transaction_id=txid_current()
   AND backend_pid=pg_backend_pid() AND event_id=p_event AND NOT attested;
 IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='audit_event_invalid'; END IF;
END $f$;
"""

EMPTY_SQL = """
CREATE FUNCTION auth.require_consumed_role_security_event() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $f$
BEGIN
 IF EXISTS(SELECT 1 FROM auth.role_security_event_intents
   WHERE transaction_id=NEW.transaction_id) THEN
   RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='mandatory_audit_event_missing';
 END IF;
 RETURN NULL;
END $f$;
"""


NEW_FUNCTIONS = (
    "CREATE FUNCTION auth.password_authentication_snapshot(p_email text)\nRETURNS TABLE(user_id uuid,password_hash text,credential_version bigint,security_version bigint)\nLANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$\n SELECT u.id,c.password_hash,c.credential_version::bigint,u.security_version::bigint\n FROM auth.users u JOIN auth.password_credentials c ON c.user_id=u.id\n WHERE u.normalized_email=p_email AND u.status='active'::auth.user_status\n$f$",
    "CREATE FUNCTION auth.password_change_snapshot(p_digest bytea)\nRETURNS TABLE(user_id uuid,password_hash text,credential_version bigint,security_version bigint)\nLANGUAGE sql STABLE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$\n SELECT u.id,c.password_hash,c.credential_version::bigint,u.security_version::bigint\n FROM auth.sessions s JOIN auth.users u ON u.id=s.user_id\n JOIN auth.password_credentials c ON c.user_id=u.id\n WHERE s.bearer_digest=p_digest AND s.revoked_at IS NULL\n AND s.idle_expires_at>statement_timestamp() AND s.absolute_expires_at>statement_timestamp()\n AND u.status='active'::auth.user_status AND s.security_version=u.security_version\n$f$",
    "CREATE FUNCTION auth.confirm_password_authentication(p_user uuid,p_credential bigint,p_security bigint,p_hash text)\nRETURNS boolean LANGUAGE plpgsql VOLATILE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$\n BEGIN\n PERFORM 1 FROM auth.password_credentials c WHERE c.user_id=p_user FOR UPDATE;\n PERFORM 1 FROM auth.users u WHERE u.id=p_user FOR NO KEY UPDATE;\n RETURN EXISTS(SELECT 1 FROM auth.users u JOIN auth.password_credentials c ON c.user_id=u.id\n WHERE u.id=p_user AND u.status='active'::auth.user_status\n AND c.credential_version=p_credential AND u.security_version=p_security AND c.password_hash=p_hash);\n END $f$",
    "CREATE FUNCTION auth.apply_password_change(p_digest bytea,p_credential bigint,p_security bigint,p_old_hash text,p_new_hash text)\nRETURNS TABLE(user_id uuid,revoked_sessions bigint)\nLANGUAGE plpgsql VOLATILE STRICT SECURITY DEFINER SET search_path=pg_catalog AS $f$\n DECLARE v_user uuid; v_count bigint; v_event uuid; v_correlation uuid := gen_random_uuid();\n BEGIN\n SELECT s.user_id INTO v_user FROM auth.sessions s WHERE s.bearer_digest=p_digest;\n IF v_user IS NULL THEN RETURN; END IF;\n IF NOT auth.confirm_password_authentication(v_user,p_credential,p_security,p_old_hash) THEN RETURN; END IF;\n PERFORM 1 FROM auth.sessions s WHERE s.bearer_digest=p_digest AND s.user_id=v_user\n AND s.revoked_at IS NULL AND s.idle_expires_at>clock_timestamp()\n AND s.absolute_expires_at>clock_timestamp() AND s.security_version=p_security FOR UPDATE;\n IF NOT FOUND THEN RETURN; END IF;\n UPDATE auth.password_credentials c SET password_hash=p_new_hash,credential_version=c.credential_version+1,\n changed_at=clock_timestamp() WHERE c.user_id=v_user;\n UPDATE auth.users u SET security_version=u.security_version+1,updated_at=clock_timestamp() WHERE u.id=v_user;\n UPDATE auth.sessions s SET revoked_at=clock_timestamp(),revoked_reason='revoke_all'\n WHERE s.user_id=v_user AND s.revoked_at IS NULL;\n GET DIAGNOSTICS v_count = ROW_COUNT;\n v_event := (lpad(to_hex(floor(extract(epoch FROM clock_timestamp())*1000)::bigint),12,'0')||'7'||substr(replace(gen_random_uuid()::text,'-',''),14))::uuid;\n PERFORM auth.append_security_event(v_event,'password_changed','success',NULL,v_user,NULL,NULL,NULL,v_correlation,NULL,NULL,NULL,NULL,NULL,NULL);\n IF v_count>0 THEN\n  v_event := (lpad(to_hex(floor(extract(epoch FROM clock_timestamp())*1000)::bigint),12,'0')||'7'||substr(replace(gen_random_uuid()::text,'-',''),14))::uuid;\n  PERFORM auth.append_security_event(v_event,'all_sessions_revoked','success','revoke_all',v_user,NULL,NULL,NULL,v_correlation,NULL,NULL,NULL,NULL,NULL,NULL);\n END IF;\n RETURN QUERY SELECT v_user,v_count;\n END $f$",
)
NEW_SIGNATURES = (
    "auth.password_authentication_snapshot(text)",
    "auth.password_change_snapshot(bytea)",
    "auth.confirm_password_authentication(uuid,bigint,bigint,text)",
    "auth.apply_password_change(bytea,bigint,bigint,text,text)",
)
RESET_COMPLETION_SQL = "CREATE OR REPLACE FUNCTION auth.complete_password_reset(p_digest bytea,p_hash text,p_event uuid,p_correlation text)\n      RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$\n      DECLARE v_token auth.password_reset_tokens%ROWTYPE; v_revoked bigint; v_correlation uuid := gen_random_uuid(); BEGIN\n       SELECT * INTO v_token FROM auth.password_reset_tokens WHERE token_digest=p_digest AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>clock_timestamp() FOR UPDATE;\n       IF NOT FOUND THEN RETURN false; END IF;\n       UPDATE auth.password_reset_tokens SET consumed_at=clock_timestamp() WHERE id=v_token.id;\n       UPDATE auth.password_reset_tokens SET revoked_at=clock_timestamp() WHERE user_id=v_token.user_id AND id<>v_token.id AND consumed_at IS NULL AND revoked_at IS NULL;\n       UPDATE auth.password_credentials SET password_hash=p_hash,credential_version=credential_version+1,changed_at=clock_timestamp() WHERE user_id=v_token.user_id;\n       IF NOT FOUND THEN RAISE EXCEPTION 'credential_missing'; END IF;\n       UPDATE auth.users SET security_version=security_version+1,updated_at=clock_timestamp() WHERE id=v_token.user_id;\n       UPDATE auth.sessions SET revoked_at=clock_timestamp(),revoked_reason='password_reset' WHERE user_id=v_token.user_id AND revoked_at IS NULL;\n       GET DIAGNOSTICS v_revoked = ROW_COUNT;\n       PERFORM auth.append_security_event(p_event,'password_reset_completed','success','password_reset',v_token.user_id,NULL,NULL,NULL,v_correlation,NULL,NULL,NULL,NULL,NULL,NULL);\n       PERFORM auth.append_security_event((substr(p_event::text,1,15)||substr(gen_random_uuid()::text,16))::uuid,'password_changed','success','password_reset',v_token.user_id,NULL,NULL,NULL,v_correlation,NULL,NULL,NULL,NULL,NULL,NULL);\n       IF v_revoked>0 THEN\n        PERFORM auth.append_security_event((substr(p_event::text,1,15)||substr(gen_random_uuid()::text,16))::uuid,'all_sessions_revoked','success','password_reset',v_token.user_id,NULL,NULL,NULL,v_correlation,NULL,NULL,NULL,NULL,NULL,NULL);\n       END IF;\n       RETURN true; END $f$"
PREVIOUS_RESET_COMPLETION_SQL = "CREATE OR REPLACE FUNCTION auth.complete_password_reset(p_digest bytea,p_hash text,p_event uuid,p_correlation text)\n      RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $f$\n      DECLARE v_token auth.password_reset_tokens%ROWTYPE; BEGIN\n       SELECT * INTO v_token FROM auth.password_reset_tokens WHERE token_digest=p_digest AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>clock_timestamp() FOR UPDATE;\n       IF NOT FOUND THEN RETURN false; END IF;\n       UPDATE auth.password_reset_tokens SET consumed_at=clock_timestamp() WHERE id=v_token.id;\n       UPDATE auth.password_reset_tokens SET revoked_at=clock_timestamp() WHERE user_id=v_token.user_id AND id<>v_token.id AND consumed_at IS NULL AND revoked_at IS NULL;\n       UPDATE auth.password_credentials SET password_hash=p_hash,credential_version=credential_version+1,changed_at=clock_timestamp() WHERE user_id=v_token.user_id;\n       IF NOT FOUND THEN RAISE EXCEPTION 'credential_missing'; END IF;\n       UPDATE auth.users SET security_version=security_version+1,updated_at=clock_timestamp() WHERE id=v_token.user_id;\n       UPDATE auth.sessions SET revoked_at=clock_timestamp(),revoked_reason='password_reset' WHERE user_id=v_token.user_id AND revoked_at IS NULL;\n       PERFORM auth.record_security_event(p_event,'password_reset_completed','success',NULL,v_token.user_id,NULL,NULL,NULL,p_correlation); RETURN true; END $f$"


def upgrade() -> None:
    for definition in (*NEW_FUNCTIONS, RESET_COMPLETION_SQL):
        op.execute(definition)
    for signature in (*NEW_SIGNATURES, "auth.complete_password_reset(bytea,text,uuid,text)"):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO sahl_migrator")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sahl_app")
    op.create_table(
        "role_security_event_intents",
        sa.Column("transaction_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("backend_pid", sa.Integer(), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        *(
            sa.Column(name, postgresql.UUID(as_uuid=True), nullable=False)
            for name in (
                "user_id",
                "session_id",
                "membership_id",
                "tenant_id",
                "role_id",
            )
        ),
        sa.Column("target_membership_id", postgresql.UUID(as_uuid=True)),
        sa.Column("permission_id", sa.String(120)),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attested", sa.Boolean(), nullable=False),
        schema="auth",
    )
    op.execute("ALTER TABLE auth.role_security_event_intents OWNER TO sahl_migrator")
    op.execute("REVOKE ALL ON TABLE auth.role_security_event_intents FROM PUBLIC,sahl_app")
    for definition in (PREPARE_SQL, ATTEST_SQL, CANCEL_SQL, EMPTY_SQL, VALIDATOR):
        op.execute(definition)
    for signature in (PREPARE, CANCEL, ATTEST, EMPTY):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO sahl_migrator")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC,sahl_app")
    for signature in (PREPARE, CANCEL):
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO sahl_app")
    for table in ("roles", "role_permissions", "membership_roles"):
        op.execute(
            f"CREATE TRIGGER role_security_change_attestation AFTER INSERT OR UPDATE OR DELETE ON auth.{table} FOR EACH ROW EXECUTE FUNCTION auth.attest_role_security_change()"
        )
    op.execute(
        "CREATE CONSTRAINT TRIGGER role_security_event_mandatory AFTER INSERT ON auth.role_security_event_intents DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION auth.require_consumed_role_security_event()"
    )


def downgrade() -> None:
    op.execute(PREVIOUS_RESET_COMPLETION_SQL)
    for signature in reversed(NEW_SIGNATURES):
        op.execute(f"DROP FUNCTION {signature}")
    op.execute("LOCK TABLE auth.role_security_event_intents IN ACCESS EXCLUSIVE MODE")
    op.execute(PREVIOUS_VALIDATOR)
    for table in ("roles", "role_permissions", "membership_roles"):
        op.execute(f"DROP TRIGGER role_security_change_attestation ON auth.{table}")
    op.execute("DROP TRIGGER role_security_event_mandatory ON auth.role_security_event_intents")
    for signature in (PREPARE, CANCEL, ATTEST, EMPTY):
        op.execute(f"DROP FUNCTION {signature}")
    op.drop_table("role_security_event_intents", schema="auth")
