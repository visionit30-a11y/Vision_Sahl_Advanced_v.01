# Phase 2D — Backend-Persisted UI Settings and Permission-Aware UI

**Status:** G1-G4 approved; G5 operationally verified against real FastAPI/PostgreSQL; awaiting owner acceptance. G6 not started.

**الأساس:** `phase-2c-baseline` عند
`e6072195079158d12dcb0ff95b0cd5343a3ba50e`، و`main = develop` عند نقطة البدء.

## نطاق المرحلة

تنقل Phase 2D مصدر حقيقة إعدادات الواجهة من adapter المتصفح المؤقت إلى Backend، وتربط
إدارة User وTenant وPlatform settings بكتالوج Phase 2C و`AuthorizationService`. تبقى
الأولوية `User → Tenant → Platform → Built-in` ودالة الحسم وDesign System والهويات
والأنماط الحالية كما هي.

خارج النطاق: Business Modules وPhase 2E وAudit Platform وإعادة تصميم نظام التصميم أو محرك
التخصيص. إخفاء controls في frontend لا يعد enforcement.

## قرارات G1

- User layer مرتبطة بـ`tenant_id + user_id`، وTenant layer مرتبطة بـ`tenant_id`، وPlatform
  layer singleton عالمية، وBuilt-in تبقى في المصدر فقط.
- تخزن الطبقات patches validated لا resolved copies، وتحمل version للتزامن المتفائل.
- User وTenant tables tenant-owned مع ENABLE + FORCE RLS؛ Platform table global بلا ادعاء
  tenant RLS. كل objects مملوكة لـ`sahl_migrator` وبأقل grants.
- permissions الجديدة المقترحة هي `tenant.user_ui_settings.manage_self` و
  `tenant.ui_settings.manage` و`platform.ui_settings.manage`، داخل الكتالوج typed فقط.
- effective API لا يقبل tenant/user selectors. الإدارة تمر عبر permission dependency ثم
  service ثم `tenant_transaction()` وRLS للمستويات tenant-owned.
- `localStorage` و`previewUiPermissions` و`preview-tenant` تزال من runtime لاحقًا. frontend
  يقرأ الحقيقة من Backend، ويعيد الجلب عند refresh وtenant switch، ولا يحتفظ بـpermission
  authority محلي.
- Platform write يبقى fail closed حتى اعتماد trusted Platform principal؛ لا tenant role
  يحمل `platform.*` ولا تنشأ AuthorizationService بديلة أو RLS bypass.

التفاصيل الكاملة في
[ADR-0024](adr/ADR-0024-backend-persisted-ui-settings.md).

## خطة G2

1. `feat(authz): add typed UI settings permissions`
   - إضافة Permission IDs الثلاثة واختبارات catalog ومنع raw strings.
2. `feat(ui-settings): add backend domain contracts`
   - patch/value/schema-version contracts وvalidators في Backend، واختبار تطابقها مع عقد
     TypeScript، بلا persistence service أو HTTP routes.
3. `feat(db): add UI settings persistence schema`
   - migration `0012_ui_settings_foundation` للجداول الثلاثة والقيود وRLS والمنح والفهارس.
4. `test(ui-settings): prove ownership and tenant isolation`
   - upgrade/downgrade/upgrade وSQL/ORM وmissing context وcross-tenant وownership/grants.
5. `docs(phase-2d): record G2 verification`
   - migration head وأعداد الاختبارات وأي قرار تغير بالدليل.

لا يبدأ G2 قبل اعتماد G1. ولا يفعل Platform write endpoint في G2.

## بوابة G1

- [x] مصادر User/Tenant/Platform/Built-in والأولوية مثبتة.
- [x] data ownership وRLS classification محددان.
- [x] Permission IDs وإدارة كل مستوى محددة.
- [x] API contracts وoptimistic concurrency وعدم قبول selectors كإثبات محددة.
- [x] migration sequence واختبارات DB/service/HTTP/browser محددة.
- [x] إزالة preview authority وbrowser persistence من runtime مخططة.
- [x] توافق Design System محفوظ بلا theme/preset أو engine redesign.
- [x] حاجز Platform principal موثق fail closed.
- [x] لا schema أو migration أو persistence code في G1.

## تنفيذ وبوابة G2

- أضيفت Permission IDs الثلاثة إلى الكتالوج typed المركزي وحده:
  `tenant.user_ui_settings.manage_self` و`tenant.ui_settings.manage` و
  `platform.ui_settings.manage`. صلاحية Platform عقد فقط ولم تستخدم في قرار أو write path.
- أضيف `UiSettingsPatch` كـRootModel مغلق: يقبل object جزئيًا من المفاتيح الستة المعتمدة
  وقيم registries الحالية فقط، ويرفض unknown keys وnull والأنواع وIDs غير المعتمدة. ثبت
  `schema_version=1` وعقد `require_self_user` الذي يرفض استهداف مستخدم آخر قبل وجود service.
- أضافت migration العكوسة `0012_ui_settings_foundation` الجداول
  `app.platform_ui_settings` و`app.tenant_ui_settings` و`app.user_ui_settings`. تخزن كلها
  patch في JSONB مع CHECKs لنوع object والمفاتيح والقيم و`version > 0`؛ لا arbitrary blob.
- `tenant_ui_settings` مفتاحها `tenant_id`. و`user_ui_settings` مفتاحها المركب
  `(tenant_id,user_id)`. كلاهما UUID tenant NOT NULL، ومملوكان لـ`sahl_migrator`، وتطبق
  عليهما ENABLE + FORCE RLS وسياسة ALL محددة لـ`sahl_app` مع USING + WITH CHECK.
- `platform_ui_settings` singleton عالمي بلا `tenant_id` ولا يدخل tenant RLS. runtime يملك
  SELECT فقط ولا يملك أي write أو ownership. لم يضف Platform write path.
- أثبتت اختبارات SQL وORM غياب السياق والعزل ورفض cross-tenant SELECT/INSERT/UPDATE/DELETE،
  ورفض المفاتيح والقيم غير الصالحة في DB، وفشل optimistic update بالنسخة القديمة، وتفرد
  user scope، وحراس catalog والملكية والمنح واكتشاف RLS.
- نجحت بوابة G2 المستهدفة: **62 passed** بلا skip أو xfail، وRuff وMypy ناجحان. نجحت دورة
  `0012 → 0011 → 0012` و`alembic check`، وأثبت حارس التنظيف 6 جداول tenant production
  بلا test artifacts. migration head هو `0012_ui_settings_foundation`.

لا توجد routes أو persistence services أو frontend integration في G2. بقي Design System
والهويات والـpresets ومحرك الحسم وملفات frontend بلا تغيير.

## خطة G3

1. repository داخلي لقراءة الطبقات وكتابتها دون كشف raw tables للخدمات الأخرى.
2. service لحسم Built-in/Platform/Tenant/User، مع `tenant_transaction()` لكل وصول tenant.
3. User writes تثبت principal self داخل العضوية الحالية؛ Tenant writes تحتاج Permission typed.
4. optimistic create/update/delete آمن تحت التزامن وDB failures تفشل مغلقًا.
5. لا HTTP routes أو frontend adapter ما لم يعتمد نطاق G3 صراحة.
6. Platform layer قراءة فقط؛ Platform writes تبقى محجوبة حتى حل trusted Platform principal.

## تنفيذ وبوابة G3

- أضيف `UiSettingsRepository` كحد persistence داخلي وحيد. يقرأ Platform settings فقط،
  ويقرأ ويكتب Tenant/User settings عبر `tenant_transaction()` وRLS دون كشف session أو raw
  tables إلى service.
- أضيف `UiSettingsService` للحسم الحتمي بالترتيب Built-in ثم Platform ثم Tenant ثم User؛
  تطغى كل طبقة على المفاتيح الموجودة فقط، وتعيد القيمة الفعالة ومصدر كل مفتاح ونسخ الطبقات.
- User writes تتطلب grant مطابقًا لـ`tenant.user_ui_settings.manage_self` وتطابق principal مع
  المستخدم المستهدف. Tenant writes تتطلب `tenant.ui_settings.manage`. لا توجد Platform write
  method أو HTTP route.
- create يستخدم insert شرطيًا، وupdate/delete يقيدان الكتابة بالنسخة المتوقعة داخل statement
  واحد. التنافس ينتج فائزًا واحدًا و`409 conflict` واضحًا للبقية؛ لا SELECT-then-write ولا
  lost update. حذف الطبقة يحذف patch فقط فتعود القيم الموروثة في الحسم التالي.
- أثبتت الاختبارات precedence وpartial patches وorigin لكل مفتاح والحذف والـpermission/self
  guards. وأثبت PostgreSQL فعليًا create/update وdelete/update races وعزل القراءة عبر RLS.
- نجحت اختبارات G3 والـregression guards المرتبطة: **99 passed** بلا skip أو xfail، وRuff
  وMypy ناجحان. migration head بقي `0012_ui_settings_foundation`.

## خطة G4

1. إضافة HTTP contracts وdependencies تستخرج principal وTenantContext الموثوقين فقط.
2. ربط effective read وUser/Tenant writes بالخدمة الحالية مع ETag/version conflict contract.
3. إثبات 401/403/409 وIDOR وcross-tenant وعدم تنفيذ repository عند DENY.
4. إبقاء Platform write وfrontend integration خارج G4 ما لم يعتمد نطاقهما صراحة.

## تنفيذ وبوابة G4

- أضيفت endpoints القراءة والحسم وإدارة طبقتي User self وTenant تحت `/ui-settings`.
  لا تقبل العقود `user_id` أو`tenant_id`؛ تأتي الهوية وTenantContext من trusted auth flow.
- كل route يرتبط بـPermission typed عبر `require_permission()`، ثم يستدعي
  `UiSettingsService` فقط. لا يوجد import أو استدعاء repository/DB من route ولا role-name check.
- User endpoints تستخدم `tenant.user_ui_settings.manage_self` وتستهدف principal الحالي فقط.
  Tenant endpoints تستخدم `tenant.ui_settings.manage` وتستهدف TenantContext الحالي فقط.
- PUT يطلب `expected_version` صراحة؛ القيمة null تعني create مشروطًا، والقيمة الموجبة تعني
  update مشروطًا. DELETE يطلب نسخة موجبة. stale state يعيد 409، والطبقة الغائبة 404،
  والتحقق 422 دون إعادة input، والمصادقة/التفويض 401/403.
- كل response لمسار UI settings، بما فيها الأخطاء، يحمل `Cache-Control: no-store`.
  لا يوجد Platform write endpoint أو frontend integration.
- أثبتت الاختبارات effective read وUser/Tenant CRUD وحدود self/context، وتجاهل selectors
  المزورة، وزيادة النسخة، و401/403/404/409/422، وغياب Platform writes وتسريب DB/session.
- نجحت بوابة G4 المستهدفة وحراس authorization/RLS المرتبطة: **83 passed** بلا skip أو
  xfail. Ruff وMypy ناجحان، وmigration head بقي `0012_ui_settings_foundation`.

## خطة G5

1. ربط frontend auth client بـeffective/User/Tenant endpoints مع credentials وCSRF الحاليين.
2. استبدال browser persistence المؤقت بالحالة المحملة من Backend، مع memory-only draft.
3. إزالة preview authority وتحديث الحالة بعد tenant switch/session rotation بلا fallback قديم.
4. إثبات التدفق بمتصفح حقيقي وحراس storage/cache/permissions مع الحفاظ على Design System.

## تنفيذ G5 — ربط Backend الفعلي

- يستخدم frontend HTTP adapter صغيرًا فوق AuthClient المشترك لمسارات effective وUser وTenant.
  لا يوجد مسار مصادقة موازٍ ولا selectors للمستخدم أو الجهة في عقود إعدادات UI.
- Backend هو مصدر settings وorigins والنسخ. تُحفظ الحالة في الذاكرة فقط، وتُطبق الكتابة
  بعد تأكيد الخادم ثم إعادة الجلب. أولوية User → Tenant → Platform → Built-in محفوظة.
- أزيلت browserUiSettingsSource وpreviewUiPermissions وUiPermissions وpreviewTenant
  وPlatform editing. لم تتغير registries أو themes أو presets أو Design System.
- refresh وme بعد المصادقة وtenant/session rotation تعيد تحميل effective settings.
  يمنع جيل الطلبات استعادة الردود القديمة، وينقل BroadcastChannel إشارة إبطال فقط.
- تعرض الواجهة loading و401 و403 و409 وفشل الشبكة بوضوح. Built-in عرض مؤقت موسوم،
  والكتابة معطلة عند تعذر تأكيد الحالة؛ لا fallback إلى localStorage أو كتابة تلقائية عند conflict.
- التشغيل المحلي الرسمي يبقى localhost:5173 و127.0.0.1:8010. localhost:5187 للاختبارات
  فقط، مع strict port ورفض الانشغال دون قتل عملية أو اختيار fallback. لم يُمس 8000 أو 5173.

### سبب المانع السابق والاعتماد الذي أغلقه

كان app/main.py يسجل api_router بالفعل، لكن HTTP handlers للجلسات لم تكن موجودة؛
لم يكن الخلل مجرد include_router مفقود. كان security-server.mjs يوفّر عقدًا للاختبارات
فقط، فيما خدمات Phase 2B وcookie/CSRF helpers موجودة دون ربط HTTP إنتاجي.
كذلك لم يكن validate_session_csrf أو Origin أو X-Expected-Membership-ID موصولًا بالطلبات.

اعتمد المالك استكمال طبقة HTTP فوق الخدمات الحالية ضمن G5، ثم اعتمد migration 0013
ودالتين محددتين مرتبطتين بالجلسة. لذلك أضيفت المسارات الفعلية التالية دون aliases:

| Method | Path | Contract |
| --- | --- | --- |
| GET | /auth/me | هوية جلسة فعالة وselectedMembershipId موثوق أو null |
| GET | /auth/memberships | عضويات المستخدم الفعالة في جهات فعالة |
| GET | /auth/csrf | 204 وX-CSRF-Token، مع Origin gate وPostgreSQL quota |
| POST | /auth/tenant/switch | 204؛ إثبات selector ثم تدوير bearer وCSRF |
| POST | /auth/logout | 204؛ إبطال الجلسة وحذف Cookie |

لم تُضف login/reset endpoints أو test-session endpoint إلى التطبيق. اختبارات المتصفح
تهيئ هويات مؤقتة في PostgreSQL وتصدر جلسة عبر خدمات Phase 2B الموجودة، ثم تستخدم
HTTP الفعلي لكل عمليات المصادقة والإعدادات قيد الاختبار.

### الحد الأمني

- migration head: `0013_auth_http_projections`.
- `auth.session_identity(bytea)` و`auth.session_memberships(bytea)` دالتان SECURITY DEFINER
  مملوكتان لـsahl_migrator، مع search_path=pg_catalog، بلا dynamic SQL أو PUBLIC EXECUTE.
  يُمنح sahl_app صلاحية EXECUTE للتوقيعين فقط؛ لا direct SELECT على users/memberships/tenants.
- projections مربوطة بـdigest جلسة لم تنتهِ ولم تُلغَ، ومستخدم فعال وsecurity_version مطابق.
  العضويات المعادة مملوكة له وفعالة داخل tenant فعال. الدالتان لا تنشئان TenantContext
  ولا تضبطان set_config ولا تغيران RLS أو FORCE RLS أو app.current_tenant_id().
- authenticated CSRF bootstrap يعيد token ثابتًا لكل bearer، مشتقًا بـHMAC-SHA256 من
  bearer عالي العشوائية ووسم `sahl-csrf-bootstrap-v1`. يُحفظ SHA-256 digest فقط.
  ثباته يسمح بـrefresh وتبويبات متوازية؛ تدوير bearer يغيّر CSRF ويبطل القيم القديمة.
- row locking يمنع سباق bootstrap/switch من استعادة bearer أو CSRF سابق. يبقى throttling
  الحقيقي في PostgreSQL عند 30/min لكل IP، ضمن transaction مستقلة تستهلك الحصة حتى عند رفض الجلسة.
- unsafe API requests تتحقق من Origin وCSRF والعضوية المتوقعة قبل خدمة الإعدادات.
  mismatch يعيد 409 مع X-Auth-Error: tenant_context_changed؛ missing/invalid يعيد 403.
  selectors لا تنشئ context، وتبقى AuthorizationService وtenant_transaction وRLS مستقلة.
- switch/logout وأحداثهما الأمنية atomic؛ فشل event إلزامي يمنع commit.
  Cookie تبقى __Host-sahl_session؛ Secure وHttpOnly وSameSite=Lax وPath=/ وبلا Domain.
- Auth/UI responses جميعها no-store، بما فيها أخطاء 500 غير المتوقعة؛ والأخطاء لا تعيد tokens. HMAC config لا يظهر في repr
  أو startup ValidationError. CSRF وbearer لا يُحفظان في browser storage أو artifacts.
- AUTH_LOCAL_HTTP_ORIGIN=http://localhost:5187 خيار اختبار صريح معطل افتراضيًا،
  مسموح في development/test فقط ومرفوض في staging/production؛ شرط HTTPS الإنتاجي محفوظ.

### دليل القبول المحلي

- Backend كامل، بما فيه Phase 2A/2B/2C وUI settings وحراس SQL/ORM/RLS: **490 passed**،
  مع --strict-security-gates وبدون skip/xfail.
- Frontend وDesign System: **225 passed / 29 files**.
- Ruff وMypy وAlembic check وESLint وTypeScript وPrettier وbuild: PASS.
- migration round-trip: 0012 → 0013 → 0012 → 0013: PASS.
- ملكية objects وgrants وRLS والتنظيف: PASS؛ sahl_app لا يملك objects ولا يكتسب table grants.
- Playwright Chromium: **7/7 passed (3.8m)** على 5187 عبر FastAPI الحقيقي على 8010 وPostgreSQL الحقيقي.
  البوابة لا تستخدم security-server ولا jsdom كإثبات أمني. التدقيق يراقب console/storage
  لكل سيناريو وتبويب، ويمنع traces/screenshots/videos وstorageState المحفوظ.
  ثبتت refresh وeffective fetch ووراثة User/Tenant وتدوير الجلسة وCSRF وإبطال القيم القديمة،
  وstale tab وOrigin أجنبي حقيقي و401/403/409 والخروج وفشل الشبكة ورفض مصادر التخزين القديمة.
  تنتظر السيناريوهات الحصة الزمنية المتاحة وفق حد CSRF الحقيقي؛ لا reset للعدادات أو retries أو skip.
- CI web gate أصبح يشغّل PostgreSQL 17، ويُعد الأدوار ويُطبق migration ويشغّل FastAPI الحقيقي قبل Chromium.
  البوابة blocking بلا skip أو continue-on-error؛ مفتاح HMAC مؤقت في ذاكرة العملية فقط.
  لا تُدّعى نتيجة GitHub CI في جولة القبول المحلية هذه.

زالت موانع قبول G5 التشغيلية. سجلا التحقق المحليان غير المتتبعين: '_logs/phase2d-g5-final-backend.log'
و'_logs/phase2d-g5-real-browser.log'. لا تتضمن سجلات الاختبار أو artifacts أسرار الجلسات.

تفاصيل التشغيل، بما فيها SelectorEventLoop على Windows، في
[browser-testing.md](browser-testing.md).

## خطة G6 المقترحة

بعد اعتماد G5: مراجعة Exit Criteria للمرحلة والبوابات النهائية وتوثيق الإغلاق المحلي،
مع تثبيت الأدلة الحالية واستكمال الفحوص المطلوبة عند نقطة قبول G6 فقط.
لم يبدأ G6؛ لا Phase 2E أو Business Modules أو Platform writes.
