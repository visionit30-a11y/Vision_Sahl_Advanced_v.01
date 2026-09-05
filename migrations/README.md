# المهاجرات

كل تغيير في Schema يمر عبر مهاجرة متسلسلة (SRS §10). ممنوع `DROP` أو إعادة Seed كاملة
كحل لمشكلة مهاجرة.

- الإعداد: `apps/api/alembic.ini` (‏`script_location = ../../migrations`).
- التشغيل من `apps/api` بعد تفعيل البيئة الافتراضية:
  - `alembic upgrade head`
  - `alembic downgrade -1`
- عنوان الاتصال يُحقن من إعدادات التطبيق، ولا يُكتب داخل `alembic.ini`.
