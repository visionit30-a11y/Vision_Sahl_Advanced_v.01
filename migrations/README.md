# المهاجرات

كل تغيير في Schema يمر عبر مهاجرة متسلسلة (SRS §10). ممنوع `DROP` أو إعادة Seed كاملة
كحل لمشكلة مهاجرة.

- الإعداد: `apps/api/alembic.ini` (‏`script_location = ../../migrations`).
- التشغيل من `apps/api` بعد تفعيل البيئة الافتراضية: `alembic upgrade head` أو `alembic downgrade -1`.
- عنوان المهاجرات `MIGRATION_DATABASE_URL` بدور `sahl_migrator`، ولا fallback إلى
  `DATABASE_URL` الخاص بـ`sahl_app` ولا عنوان مكتوب داخل `alembic.ini`.
- يُرفض دور التطبيق قبل تطبيق المهاجرات. تتحقق البوابة من head الفعلي وتفشل عند الخطأ.

## سلسلة Phase 2A

| المعرّف | الغرض |
|---|---|
| `0002_tenant_foundation` | أساس الجهة ومخطط `app` |
| `0003_tenant_context_function` | قارئ السياق transaction-local ومنحه المحددة |
| `0004_runtime_privilege_boundary` | سحب المنح القديمة من `tenants` وdefault grants الواسعة |
| `0005_auth_identity_foundation` | مخطط الهوية العالمي وجدولا المستخدمين والعضويات وحدود الوصول |
| `0006_password_credentials` | اعتماد Argon2id المنفصل ونسخة الاعتماد وتاريخ تغييره |
| `0007_server_side_sessions` | جلسات PostgreSQL digest-only وحالة pre-auth CSRF |
| `0008_trusted_membership` | اختيار العضوية في الجلسة ووظيفة تحقق bootstrap محددة |
| `0009_auth_security_controls` | عدادات PostgreSQL الذرية، reset tokens digest-only، وسجل أحداث الأمان |

حل `0004_runtime_privilege_boundary` محل اسم `0004_tenant_isolation_policies` المخطط
سابقًا، بعد اعتماد أن `public.tenants` جدول منصّة بلا tenant RLS وبلا منح runtime.
لا جدول أو سياسة إنتاج في 0004؛ تسحب فقط المنح القديمة للتطبيق وPUBLIC من `tenants`،
وتزيل default grants الواسعة للتطبيق على جداول وتسلسلات المهاجر في `public`.

تعيد `downgrade` حالة 0003 المعروفة: CRUD للتطبيق على `tenants`، وCRUD الافتراضي للجداول،
وUSAGE/SELECT الافتراضي للتسلسلات. بعد اختبار العكس تُعاد القاعدة إلى head؛ حدود 0004 هي
حالة التشغيل المطلوبة. دورة `downgrade base → upgrade head` تُفحص على PostgreSQL الحقيقي.

`tenant_scoped_probe` **ليست مهاجرة**: تنشئها fixture اختبار بدور المهاجر ثم تسقطها
في teardown مع آثارها. لا إنتاج لجدول probe أو نوع أو دالة أو تسلسل اختبار دائم.
هذا التفكيك المقصود ليس استخدام DROP لإصلاح مهاجرة.

التفصيل في [ADR-0016](../docs/adr/ADR-0016-tenant-rls-enforcement.md)
و[ADR-0017](../docs/adr/ADR-0017-database-role-separation.md).
