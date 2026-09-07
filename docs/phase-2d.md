# Phase 2D — Backend-Persisted UI Settings and Permission-Aware UI

**الحالة:** Group 1 منفذة توثيقيًا وتنتظر اعتماد المالك.

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
