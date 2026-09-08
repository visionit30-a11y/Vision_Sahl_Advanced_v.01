# ADR-0024: تخزين إعدادات الواجهة في Backend وربطها بالتفويض

- **الحالة:** معتمد للتنفيذ في Phase 2D — Group 1
- **التاريخ:** 2026-09-07
- **المرحلة:** Phase 2D

## السياق

محرك التخصيص الحالي يحسم ستة مفاتيح ثابتة عبر `resolveUiSettings` ويطبقها عبر
`applyUiSettings`. التخزين في `localStorage`، و`preview-tenant`، و`previewUiPermissions`
كانت seams مؤقتة قبل وجود Tenancy وAuthentication وRBAC. بعد baseline Phase 2C أصبحت
الهوية والعضوية و`TenantContext` و`AuthorizationService` هي الحدود الموثوقة، ولذلك يجب أن
تصير قاعدة البيانات مصدر الحقيقة وأن تكون الكتابة محمية بصلاحيات الكتالوج المركزي.

هذا القرار لا يغير Design System أو الهويات أو الأنماط أو دالة الحسم. إنه يحدد التخزين
والملكية وواجهات API التي ستغذي العقد القائم لاحقًا.

## القرار

### 1. الطبقات وترتيب الأولوية

يبقى الحسم لكل مفتاح مستقلًا وبالترتيب النهائي:

`User → Tenant → Platform → Built-in`

- **User:** اختيار المستخدم داخل الجهة الحالية. هو override مرتبط بـ`user_id + tenant_id`؛
  لا ينتقل اختيار المستخدم في جهة إلى جهة أخرى.
- **Tenant:** اختيار الجهة الحالية، ويطبق على أعضائها ما لم يتجاوزه اختيار User.
- **Platform:** افتراض persisted عالمي يسبق Built-in ولا يمنح أي وصول إلى بيانات الجهات.
- **Built-in:** الثوابت المصدرية الحالية في frontend، غير مخزنة في DB ولا قابلة للكتابة.

كل طبقة persisted تحمل **patch** فقط. غياب المفتاح يعني الوراثة من الطبقة الأدنى، وpatch
الفارغة تعني حذف الطبقة. لا تخزن النتيجة المحسومة كي لا تتحول القيم الموروثة إلى نسخ راكدة.

### 2. عقد القيم والتحقق

تبقى المفاتيح الستة الحالية وحدها: `theme` و`buttonPreset` و`alertPreset` و
`overlayPreset` و`tablePreset` و`printPreset`. القيم هي IDs المعتمدة في registries الحالية؛
لا يضيف Phase 2D theme أو preset جديدًا.

يقبل Backend JSON object محدودًا بهذه المفاتيح، ويرفض المفتاح أو النوع أو ID غير المعتمد.
لا تمرر قاعدة البيانات JSON اعتباطية إلى DOM. يكرر Backend كتالوج IDs كعقد API typed،
وتثبت اختبارات contract مطابقته لكتالوج TypeScript. الاستجابة تحمل `schema_version=1`،
وكل صف يحمل `version` موجبة للتحديث المتفائل.

### 3. نموذج البيانات المقترح

كل الجداول في مخطط `app` ويملكها `sahl_migrator`:

| الجدول | المفتاح | البيانات | التصنيف |
|---|---|---|---|
| `app.platform_ui_settings` | صف singleton ثابت | `settings jsonb`, `version`, audit timestamps/actor | Platform-global |
| `app.tenant_ui_settings` | `tenant_id` | `settings jsonb`, `version`, audit timestamps/actor | Tenant-owned |
| `app.user_ui_settings` | `(tenant_id, user_id)` | `settings jsonb`, `version`, audit timestamps | Tenant-owned user override |

تتحقق CHECK constraints من أن `settings` object، وأن مفاتيحه subset معروفة، وأن `version > 0`.
التحقق الدلالي الكامل للـIDs في domain/service قبل الكتابة، ويعاد عند القراءة fail closed؛
القيمة المخزنة غير الصالحة لا تطبق ولا تعاد إلى العميل كقرار صالح.

`user_ui_settings.user_id` يشير إلى `auth.users`، و`tenant_id` إلى `public.tenants`. الخدمة
تثبت عضوية principal الحالية ونشاطها ونسختها قبل قراءة أو كتابة User layer. لا يقبل API
`user_id` أو `tenant_id` من العميل لإثبات الملكية.

### 4. الملكية وRLS والمنح

- `tenant_ui_settings` و`user_ui_settings` تحملان `tenant_id UUID NOT NULL` وتطبقان
  `ENABLE RLS` و`FORCE RLS` وسياسة `USING + WITH CHECK` المعتمدة حرفيًا مع
  `app.current_tenant_id()`. كل وصول داخل `tenant_transaction()`.
- `platform_ui_settings` جدول عالمي بلا `tenant_id`، لذلك لا يدعي tenant RLS. لا يملك
  `sahl_app` أي object، وتقتصر grants على العمليات التي يحتاجها repository الداخلي.
- RLS يبقى حد العزل بين الجهات، و`AuthorizationService` حد السماح بالفعل داخل الجهة.
  RLS وحده لا يثبت أن المستخدم يملك User row داخل الجهة.
- لا `BYPASSRLS` أو `row_security=off` أو migrator runtime أو SECURITY DEFINER لتجاوز
  التفويض. routes لا تصل إلى الجداول مباشرة.

### 5. Permission IDs

تضاف إلى `Permission` المركزية فقط:

| Permission ID | الاستعمال |
|---|---|
| `tenant.user_ui_settings.manage_self` | إدارة User layer للمستخدم المثبت داخل الجهة الحالية |
| `tenant.ui_settings.manage` | إدارة Tenant layer للجهة الحالية |
| `platform.ui_settings.manage` | إدارة Platform layer بعد وجود Platform principal موثوق |

قراءة الإعدادات الفعالة جزء من bootstrap للمستخدم المصادق و`TenantContext` الموثوق، وليست
دليل صلاحية أو مصدر authority. endpoints الإدارية للطبقة الخام تستخدم Permission ID typed؛
إخفاء control في frontend تحسين UX فقط، والـAPI يعيد القرار من `AuthorizationService`.

لا تمنح tenant role صلاحية `platform.*`. ولا تستخدم role name أو permission string خارج
الكتالوج.

### 6. عقود API

جميع الاستجابات `Cache-Control: no-store` ولا تقبل tenant/user selectors كإثبات:

| العقد | التفويض | النتيجة |
|---|---|---|
| `GET /ui-settings/effective` | session + trusted `TenantContext` | full settings + origin لكل مفتاح + versions |
| `GET /ui-settings/user` | `tenant.user_ui_settings.manage_self` | User patch الحالية وversion |
| `PUT /ui-settings/user` | الصلاحية نفسها | استبدال patch كاملًا مع `expected_version` |
| `DELETE /ui-settings/user` | الصلاحية نفسها | حذف layer والعودة للوراثة |
| `GET /ui-settings/tenant` | `tenant.ui_settings.manage` | Tenant patch وversion |
| `PUT /ui-settings/tenant` | الصلاحية نفسها | استبدال متفائل داخل tenant transaction |
| `DELETE /ui-settings/tenant` | الصلاحية نفسها | حذف Tenant layer |
| `GET/PUT/DELETE /platform/ui-settings` | `platform.ui_settings.manage` | عقد محجوز حتى حل Platform principal |

`PUT` يتطلب version معروفة؛ التعارض يعيد `409` بلا lost update. الحذف idempotent وفق version
العقدية. أخطاء cross-tenant وIDOR غير كاشفة، وفشل DB يفشل مغلقًا ولا يعيد local fallback.

### 7. ربط frontend وإزالة preview authority

يستبدل adapter HTTP تطبيق `browserUiSettingsSource`. يحمل application bootstrap نتيجة
`GET /ui-settings/effective` ويطبقها قبل عرض shell بقدر ما يسمح مسار التحميل، ثم يعيد
الجلب بعد tenant switch. User patch تدخل إلى `resolveUiSettings` عبر الحقل الموجود أصلًا.

`localStorage` لا يعود مصدر settings ولا fallback. لا تخزن patches أو permission snapshot
في `localStorage` أو `sessionStorage` أو IndexedDB. يمكن حفظ state غير سرية في الذاكرة
للجلسة، لكن أي refresh أو tenant switch يعيد الحقيقة من Backend.

تحذف `previewUiPermissions` و`PREVIEW_TENANT_ID` من runtime. صفحة Design System قد تستخدم
state محلية صريحة للعرض التجريبي فقط، بلا persistence وبلا ادعاء صلاحية. صلاحية عناصر
الإدارة في UI تأتي من contract خادمي مشتق من الكتالوج؛ تعديل DOM أو استدعاء API يدويًا لا
يتجاوز enforcement الخادمي.

### 8. حاجز Platform Admin

Phase 2C وثقت Platform Admin ولم تنشئ platform assignment أو trusted Platform principal.
لذلك تعريف `platform.ui_settings.manage` آمن، لكن **تفعيل** write endpoint الخاص بالمنصة
محجوب حتى يعتمد وينفذ مصدر موثوق لهذه الصلاحية داخل `AuthorizationService` المركزية.

لا يحل الحاجز بإسناد `platform.*` إلى tenant role، أو باختيار preview tenant، أو بإعفاء
جدول المنصة، أو بخدمة تفويض ثانية. يمكن إنشاء الجدول وقراءة Platform layer خلال Phase 2D،
أما الإدارة runtime فتظل disabled/fail closed حتى القرار المعتمد.

## تسلسل Migration والتنفيذ

1. توسيع Permission catalog والعقود typed مع guards؛ بلا endpoint.
2. migration واحدة `0012_ui_settings_foundation` بعد `0011_role_administration_guards`:
   الجداول والقيود والفهارس والملكية والمنح وRLS، وعكس كامل.
3. repositories داخلية وservice للحسم وUser/Tenant writes داخل transaction واحدة.
4. HTTP contracts الفعالة والإدارية مع optimistic concurrency وnegative tests.
5. HTTP frontend adapter وpermission-aware controls، ثم حذف browser/preview runtime paths.
6. Browser/security gates وإغلاق الوثائق. Platform write لا يفعل قبل حل الحاجز أعلاه.

## استراتيجية الاختبار

- **Contract:** تطابق المفاتيح والـIDs بين Python وTypeScript، patches جزئية، unknown keys/
  values، precedence لكل مفتاح، origin map، schema version.
- **DB:** upgrade/downgrade/upgrade، ownership/grants، ENABLE + FORCE، USING + WITH CHECK،
  missing context، SQL/ORM cross-tenant CRUD، composite identity، cleanup guard.
- **Service:** user/tenant/platform/built-in precedence، self ownership، inactive/stale
  membership، optimistic conflict، concurrent writes، deletion fallback، invalid stored row.
- **Authorization/HTTP:** missing principal/context، typed permissions، unauthorized writes،
  IDOR user/tenant selectors، no service execution on DENY، no role-name checks، DB failure.
- **Frontend/browser:** Backend source only، no preview authority، no storage persistence،
  refresh consistency، tenant switch invalidation، 401/403، stale version، no-store، وفشل
  تعديل frontend controls في تجاوز API.
- **Compatibility:** اختبارات resolver وtheme/preset registries وDesign System وRTL/LTR و
  WCAG وbuild تبقى بلا تغيير بصري.

## البدائل المرفوضة

- localStorage أو IndexedDB كمصدر حقيقة أو fallback بعد فشل Backend.
- تخزين resolved settings بدل patches.
- user override عالمي بلا tenant binding.
- frontend permission hiding كضابط أمان.
- preview tenant أو header أو body tenant ID كإثبات.
- منصة تدير global settings بصلاحية tenant أو عبر RLS bypass.
- إعادة بناء المحرك أو تغيير theme/preset registries بسبب persistence.

## النتائج

يبقى محرك العرض الحالي كما هو، وينتقل مصدر طبقاته إلى Backend بعقود typed وتوريث قابل
للتفسير. User وTenant يبقيان داخل TenantContext وRLS، وPlatform يبقى عالميًا لكن يفشل
مغلقًا في الكتابة حتى يوجد principal موثوق. لا ينشئ G1 schema أو migration أو runtime code.
