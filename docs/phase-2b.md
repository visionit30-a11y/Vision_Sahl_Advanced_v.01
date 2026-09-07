# Phase 2B — Identity, Authentication, Memberships and Server-Side Sessions

**الحالة:** Group 2 — أساس الهوية والعضويات منفذ محليًا؛ ينتظر قبول المالك.

**الأساس:** `phase-2a-baseline` عند `cc58409f13573b5269d740f63e8f801295eb7ea1`.

## النطاق

يدخل في المرحلة: users، tenant memberships، password credentials، Argon2id، دورة الحساب،
PostgreSQL server-side sessions، cookies، CSRF، الإبطال والخروج والانتهاء، trusted membership
resolution إلى `TenantContext`، PostgreSQL throttling، password-reset foundation، MFA
readiness، أحداث المصادقة المحدودة، واختبارات الأمن والبوابات.

خارج النطاق: RBAC، permissions، Authorization Service، Platform Admin bypass، JWT كجلسة
أساسية، Redis كمصدر حقيقة، SSO/OAuth، full MFA، notifications، UI settings persistence،
محركات الجداول والتقارير، ووحدات الأعمال.

## العقود الموروثة

لا تغير المرحلة `TenantContext` أو RLS وFORCE أو `set_config(..., true)` أو
`app.current_tenant_id()` أو فصل أدوار `sahl_app`/`sahl_migrator` أو تصنيف `tenants`
Platform-level أو fail-closed behavior.

تسلسل الثقة:

```text
valid credentials/session
  → active user
  → active membership owned by that user
  → active tenant
  → authenticated principal
  → unchanged TenantContext
  → unchanged Phase 2A transaction boundary
  → PostgreSQL RLS
```

كل tenant identifier من header أو body أو query أو cookie أو subdomain هو selector فقط.

## المجموعات

| Group | المحتوى | الحالة |
|---|---|---|
| G1 | ADRs والقرارات الأمنية | مقبول للمتابعة عند `afdf2cd` |
| G2 | users + tenant_memberships + schema | منفذ محليًا؛ ينتظر قبول المالك |
| G3 | password credentials + Argon2id | لم يبدأ |
| G4 | sessions + cookies + CSRF | لم يبدأ |
| G5 | trusted membership resolution → TenantContext | لم يبدأ |
| G6 | throttling + reset foundation + security events | لم يبدأ |
| G7 | frontend auth client + browser/security gates | لم يبدأ |
| G8 | التحقق النهائي والتوثيق | لم يبدأ |

## القرارات

| ADR | الموضوع |
|---|---|
| ADR-0018 | الهوية والعضوية والاستثناء المحدد وحد bootstrap |
| ADR-0019 | كلمات المرور وArgon2id والاستعادة |
| ADR-0020 | جلسات PostgreSQL ودورتها وتبديل الجهة |
| ADR-0021 | cookies وCSRF وthrottling وبوابة المتصفح |
| ADR-0022 | أحداث المصادقة والخصوصية والاحتفاظ |

## قواعد التنفيذ

- commits ذرية واختبارات متناسبة بعد كل مجموعة.
- PostgreSQL 17 حقيقي للسلوك الحساس للقاعدة؛ لا SQLite أو mock بديلًا عن الدليل.
- security gates blocking، بلا SKIP/XFAIL/XPASS أو `continue-on-error`.
- لا تنفيذ للمجموعة التالية قبل قبول الحالية.
- لا تغير BRD/SRS؛ كل انحراف أو قرار جديد يسجل في ADR.
- لا أسرار حقيقية في fixtures أو logs أو exceptions أو commits.
## بوابة G1

- توثيق البدائل والحدود والقرارات قبل schema: مكتمل.
- استثناء العضوية محدود ومسمى: مكتمل في ADR-0018.
- عقود Phase 2A محفوظة نصًا: مكتمل.
- قرارات كلمات المرور والجلسات وCSRF والحدود والخصوصية موثقة: مكتمل.
- لا code أو migration أو dependency في G1: ملتزم.

## تنفيذ وبوابة G2

- أنشأت Migration `0005_auth_identity_foundation` مخطط `auth` ونوعي الحالة وجدولي
  `users` و`tenant_memberships` بملكية `sahl_migrator`.
- المستخدم عالمي بلا `tenant_id`، والعضوية تحمل FK صريحًا إلى المستخدم والجهة، وقيدي
  التفرد `(user_id, tenant_id)` و`(id, user_id)` استعدادًا لمرجع الجلسة المركب.
- لا role/permission placeholder، ولا grants بيانات لـ`sahl_app` أو `PUBLIC`.
- بقيت العضوية مرئية لحارس `tenant_id`. يطبق الحارس استثناء ADR-0018 المحدد، ويرفض
  RLS غير المعتمد، أو حذف FK، أو إضافة عمود أعمال، أو منح runtime/PUBLIC.
- دورة المهاجرة الجديدة فقط نجحت: `0005 → 0004 → 0005`. بقيت Phase 2A دون downgrade.
- اختبارات القبول المستهدفة: **60 passed** مع strict security gates، ثم حارس التنظيف PASS
  وأثبت جدول tenant-id إنتاجيًا واحدًا هو العضوية المعتمدة.
- Migration head بعد التحقق: `0005_auth_identity_foundation`.
