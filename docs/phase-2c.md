# Phase 2C — RBAC and Central Authorization Service

**الحالة:** Groups 1–4 معتمدة؛ Group 5 منفذ محليًا وبوابة Phase 2C جاهزة للمراجعة.

**الأساس:** `phase-2b-baseline` عند
`297eeaaaa40a9d66a42876505804699fd1e920ca`، و`main = develop` عند نقطة البدء.

## الهدف والحدود

تضيف Phase 2C صلاحيات ثابتة، وأدوارًا مرتبطة بالجهة، وخدمة تفويض مركزية فوق
`AuthenticatedPrincipal` و`TenantContext`. لا تغير `TenantContext` أو RLS وFORCE أو
`app.current_tenant_id()` أو `set_config(..., true)` أو تصميم الجلسات.

G1 توثيق فقط. لا schema أو migration أو authorization runtime code أو Business Modules أو
UI permissions implementation أو Phase 2D.

## عقود G1

- Permission IDs ثابتة ومركزية بصيغة `<scope>.<resource>.<action>`.
- الخدمات تطلب permission ولا تفحص role name.
- الأدوار tenant-scoped، وربط العضوية والدور والصلاحية مقيد بالجهة نفسها.
- Authorization Service هي نقطة القرار الوحيدة، وتفشل مغلقًا.
- التفويض لا يستبدل RLS ولا يملك أي bypass لها.
- Platform Admin عالمي للـplatform permissions؛ عمليات بيانات الجهة تظل بسياق صريح وRLS.
- استراتيجية IDOR وcross-tenant السلبية جزء من بوابة كل endpoint لاحق.

التفاصيل والبدائل المرفوضة في
[ADR-0023](adr/ADR-0023-central-authorization-and-rbac.md).

## خطة commits لـG2

1. `feat(authz): add typed permission catalog and role domain contracts`
   - Permission ID type والكتالوج والتحقق واختبارات العقود فقط.
2. `feat(db): add tenant-scoped RBAC schema`
   - migration مستقلة بعد `0009_auth_security_controls` للجداول والقيود والفهارس والـRLS
     والمنح، مع upgrade/downgrade/upgrade.
3. `test(authz): enforce RBAC catalog and tenant isolation guards`
   - catalog/ownership/grants/RLS/cross-tenant FK tests وحارس منع role-name checks.
4. `docs(phase-2c): record G2 verification`
   - الرأس الجديد، أعداد الاختبارات، migration head، وأي قرار تغير بعد دليل PostgreSQL.

لا يبدأ تنفيذ G2 قبل اعتماد G1.

## بوابة G1

- [x] ADR يحدد naming والrole model والتدفق المركزي.
- [x] العلاقة بين User وMembership وRole وPermission وTenantContext محددة.
- [x] تصنيف جداول RBAC وPlatform Admin موثق بلا إعفاء شامل.
- [x] RLS وFORCE وTenantContext وعقود Phase 2A/2B محفوظة.
- [x] مصفوفة اختبارات IDOR وcross-tenant محددة للمجموعات اللاحقة.
- [x] لا schema أو migration أو authorization implementation في G1.

## تنفيذ وبوابة G2

- أضيف catalog typed وحيد لست Permission IDs تخص الهوية والأدوار والجهات، مع تحقق
  `<scope>.<resource>.<action>` ورفض المعرفات المكررة أو غير الصالحة وحارس يمنع نسخها في
  ملفات التطبيق الأخرى.
- أضيفت عقود `RoleId` و`RoleKey` و`RoleStatus` ونماذج `Role` و`RolePermission` و
  `MembershipRole`. لا توجد خدمة قرار أو HTTP enforcement في هذه المجموعة.
- أضافت migration العكوسة `0010_tenant_rbac_foundation` الجداول `auth.roles` و
  `auth.role_permissions` و`auth.membership_roles`، والقيود المركبة التي تمنع ربط دور أو
  عضوية من جهة أخرى.
- تحمل الجداول الثلاثة `tenant_id UUID NOT NULL`، ويملكها `sahl_migrator`، وتطبق
  `ENABLE` و`FORCE RLS` وسياسة واحدة محددة لـ`sahl_app` مع `USING` و`WITH CHECK`.
  منح runtime هي CRUD غير قابلة للمنح اللازمة لإثبات RLS، بلا ownership أو DDL أو
  `BYPASSRLS` أو منح لـPUBLIC.
- نجحت دورة `0010 → 0009 → 0010` و`alembic check`، وبقي head
  `0010_tenant_rbac_foundation`.
- بوابة G2 المستهدفة تشمل domain/catalog، وSQL وORM، وغياب السياق، وعمليات cross-tenant،
  والقيود المركبة، وحراس RLS والملكية والمنح، وحراس Phase 2A/2B المرتبطة. أثبت حارس
  التنظيف أربع جداول production تحمل `tenant_id` وبلا artifacts. النتيجة: **73 passed**،
  وRuff وMypy وAlembic check ناجحة.

## تنفيذ وبوابة G3

- أضيفت `AuthorizationService` كنقطة القرار الوحيدة بعقد typed يعيد `ALLOW` أو `DENY`
  فقط من `AuthenticatedPrincipal` و`TenantContext` و`PermissionId`.
- repository داخلي لا يصدر session أو جداول RBAC. يفتح `tenant_transaction()` بالسياق
  المثبت، ويتحقق من الجلسة الحالية ونسخة العضوية وحالة المستخدم والعضوية والجهة عبر
  resolver الموثوق في Phase 2B، ثم يحسب الصلاحية من `membership_roles` واتحاد
  `role_permissions` للأدوار النشطة فقط.
- لا cache أو Redis أو fallback. كل قرار يقرأ الحالة الحالية، لذلك يظهر تعطيل الدور أو حذف
  permission أو assignment في القرار التالي مباشرة.
- المدخل المفقود أو المزور، mismatch الجهة، membership قديمة، غياب الدور أو الصلاحية،
  الدور غير النشط، وأي فشل dependency تنتج `DENY`. Permission ID صحيحة الصيغة لكنها غير
  موجودة في catalog ترفض قبل فتح قاعدة البيانات.
- حارس static يمنع قرار `authorize` ثانٍ أو وصولًا إلى جداول RBAC من ملفات التطبيق خارج
  الخدمة المركزية وتعريفات النماذج، ويستمر حارسا permission literals وrole-name checks.
- بوابة G3 المستهدفة: **88 passed**. نجحت Ruff وMypy وحراس PostgreSQL وPhase 2A/2B/G2،
  وأثبت حارس التنظيف أربع جداول production تحمل `tenant_id` وبلا artifacts. بقي migration
  head هو `0010_tenant_rbac_foundation` بلا migration جديدة في G3.

## تنفيذ وبوابة G4

- أضيف `require_permission(Permission)` كحد FastAPI مركزي. يقرأ جلسة HttpOnly عبر resolver
  Phase 2B، ويحصل على `AuthenticatedPrincipal` و`TenantContext` المثبتين، ثم يستدعي
  `AuthorizationService`. لا route تقرأ role أو permission string أو تتخذ القرار.
- ينتج ALLOW فقط `AuthorizationGrant` typed، وإنشاء هذا العقد محصور بحارس static في
  dependency المركزية. DENY يعيد 403 عامة قبل استدعاء الخدمة، وغياب session يعيد 401.
- أضيفت واجهتا قراءة محدودتان لمورد العضوية الموجود: العضوية الحالية والعضوية المحددة بـUUID.
  لا تقبل الخدمة استدعاءً دون grant. UUID هو selector فقط؛ أي UUID غير العضوية المثبتة يعيد
  404 موحدة لا تكشف هل المورد موجود أو تابع لجهة أخرى.
- لا يمنح header أو frontend hint أي authority. يبقى قرار التفويض داخل الخدمة المركزية،
  وقراءة RBAC الفعلية داخل `tenant_transaction()` وتحت RLS. لم تتغير سياسات RLS أو عقود
  Phase 2A/2B/G2/G3، ولم يضف Business Module.
- بوابة G4 المستهدفة: **112 passed**. نجحت Ruff وMypy وAlembic check وحراس PostgreSQL
  والتنظيف والملكية والمنح، وبقي head `0010_tenant_rbac_foundation`.

## تنفيذ وبوابة G5

- أضيفت خدمة `RoleAdministrationService` كحد الكتابة الوحيد لجداول RBAC. تنشئ الأدوار
  وتحدث أسماءها وتعطلها، وتربط/تفك Permission IDs typed، وتربط/تفك الأدوار بالعضويات.
  routes لا تصل إلى الجداول مباشرة، وكل عملية تحتاج `AuthorizationGrant` ناتجًا من
  `require_permission(Permission)` المركزي.
- كل كتابة تفتح `tenant_transaction()` واحدة وتبقى تحت FORCE RLS. تستخدم إضافة
  assignments `ON CONFLICT DO NOTHING` لتكون idempotent وآمنة عند التزامن، بينما تستخدم
  تغييرات الدور `version` متفائلة وترفض النسخة القديمة دون فقد تحديث.
- أضافت migration العكوسة `0011_role_administration_guards` عمود نسخة الدور ودالة
  `auth.is_active_membership_in_tenant(uuid,uuid)` الضيقة. الدالة `SECURITY DEFINER`
  مملوكة لـ`sahl_migrator`، و`search_path=pg_catalog`، بلا dynamic SQL أو PUBLIC EXECUTE،
  ولا تضبط TenantContext أو تمنح وصولًا عامًا للجداول.
- UUIDs المقدمة من العميل selectors فقط. يتحقق الخادم من الدور والعضوية النشطين داخل
  الجهة؛ RLS يخفي الدور الأجنبي، والدالة الضيقة ترفض العضوية الأجنبية أو غير النشطة،
  وتعود أخطاء 404/403 عامة بلا كشف وجود المورد.
- إزالة permission وتعطيل الدور يظهران في قرار `AuthorizationService` التالي فورًا؛ لا
  cache أو Redis أو fallback. صلاحية `platform.*` لا تقبلها خدمة إدارة tenant roles.
- Platform Admin لم يحصل على bypass أو وصول عالمي. العقد المستقبلي فقط:
  `trusted tenant selection → one TenantContext → AuthorizationService →`
  `tenant_transaction() → RLS`، مع حظر BYPASSRLS و`row_security=off` وsuperuser والمعاملة
  العابرة للجهات.
- نجحت دورة migration `0011 → 0010 → 0011` و`alembic check`. بوابة Phase 2C المستهدفة
  شغلت **162 passed**: 88 لعقود catalog/service/HTTP وإدارة الأدوار، و74 لحراس RLS
  وSQL/ORM والعزل والملكية والمنح وPhase 2A/2B. نجحت Ruff وMypy، وحارس التنظيف أثبت
  4 جداول tenant production وبلا test artifacts.

## Exit Criteria المحلية لـPhase 2C

- [x] Permission IDs typed ومركزية ولا توجد raw literals خارج catalog.
- [x] لا role-name checks ولا AuthorizationService بديلة أو قرارات متناثرة.
- [x] الأدوار والروابط tenant-owned بقيود مركبة وENABLE + FORCE RLS.
- [x] ALLOW/DENY يفشل مغلقًا ويقرأ الحالة الحالية بلا cache أمني.
- [x] API enforcement يسبق تنفيذ الخدمة ويستخدم principal وTenantContext موثوقين.
- [x] إنشاء وتحديث وتعطيل الدور محمي ومتزامن بأمان.
- [x] ربط وفك permissions والأدوار idempotent ولا ينشئ duplicates.
- [x] IDOR وcross-tenant selectors مرفوضة دون كشف وجود المورد.
- [x] إزالة permission وتعطيل role ينعكسان فورًا على القرار التالي.
- [x] Platform Admin لا يملك tenant bypass أو مسارًا يعطل RLS.
- [x] migration عكوسة وhead هو `0011_role_administration_guards`.
- [x] حراس Phase 2A/2B والملكية والمنح والتنظيف باقية ناجحة.

النتيجة المحلية: **12/12 PASS**. Phase 2C جاهزة لمراجعة المالك وإنشاء PR بعد اعتماده؛
لم يبدأ Phase 2D أو Business Modules أو UI permissions implementation.
