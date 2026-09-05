# Phase 0 — Repository & Local Foundation

**المرجع:** SRS §15 (Phase 0) · BRD §16 (Workstream 0) · ADR-0001

## الهدف

تأسيس مستودع وبيئة تشغيل محلية قابلة للتشغيل والاختبار، **بلا أي منطق أعمال**.

## النطاق المنفَّذ

- تهيئة Git والفروع `main` / `develop` / `feature/phase-0-foundation` وربط المستودع الرسمي.
- بنية المستودع وفق SRS §4 وADR-0002.
- هيكل FastAPI: إعدادات من البيئة، Structured Logging بـ Correlation ID، شكل خطأ موحد،
  طبقات Routers/Services، ونقاط الفحص الصحي.
- طبقة قاعدة البيانات (SQLAlchemy غير متزامن) + Alembic ومهاجرة أساس فارغة.
- طبقة Redis (مزوّد اتصال + إعداد + فحص صحي) دون تشغيل فعلي — ADR-0003.
- هيكل React + Vite + TypeScript وصفحة تحقق تقنية واحدة.
- أدوات الجودة: Ruff, mypy, pytest / ESLint, Prettier, tsc, Vitest.
- سكربتات التشغيل في `scripts/` وسجلات في `_logs/` — ADR-0004.
- تكامل مستمر بسيط في `.github/workflows/ci.yml`.

## خارج النطاق صراحة

Finance · HR · Governance · Beneficiaries · Purchasing · Inventory · Projects · Tenancy ·
RLS الفعلي · Authentication · RBAC · Workflow · Approvals · Audit Engine · Documents Engine ·
Notifications · أي جدول أعمال · أي شاشة أعمال · نظام التصميم وi18n (Phase 1).

> صفحة الواجهة في هذه المرحلة **صفحة تحقق تقنية مؤقتة** وليست بداية تصميم المنصة، وتُستبدل
> بالكامل في Phase 1 بقشرة ثنائية اللغة مبنية على نظام التصميم وطبقة i18n.

## معايير القبول (بعد تعديل بند Redis)

| # | المعيار | الحالة |
|---|---|---|
| 1 | فروع `main` / `develop` / `feature/phase-0-foundation` قائمة والمستودع الرسمي مربوط | ✅ محليًا |
| 2 | لا أسرار ولا `.env` في تاريخ Git | ✅ |
| 3 | الخلفية تعمل و`/health` يستجيب | ⏳ يتطلب تشغيل السكربت |
| 4 | `/health/db` يستجيب `up` مقابل PostgreSQL محلي | ⏳ |
| 5 | `/health/redis` يستجيب `disabled` بوضوح دون ادعاء نجاح | ⏳ |
| 6 | الواجهة تعمل وتقرأ حالة الخلفية | ⏳ |
| 7 | Alembic يطبّق مهاجرة الأساس ويتراجع عنها | ⏳ |
| 8 | دور التطبيق بلا `SUPERUSER` وبلا `BYPASSRLS` (يتحقق منه السكربت) | ⏳ |
| 9 | `ruff` + `mypy` + `pytest` بلا أخطاء | ⏳ |
| 10 | `eslint` + `tsc --noEmit` + `vitest` + `build` بلا أخطاء | ⏳ |
| 11 | لا منطق أعمال ولا جدول مجال ولا شاشة أعمال | ✅ |
| 12 | Commits ذرّية وتقرير تغيير واضح | ✅ |

**معيار مُستثنى بقرار موثق:** تشغيل Redis محليًا (ADR-0003) — مؤجل إلى Phase 3،
ولا يمنع إغلاق Phase 0.

## قيود بيئة موثقة

| القيد | الأثر |
|---|---|
| تعذر تنفيذ أوامر على ويندوز من الوكيل | التشغيل والاختبار عبر سكربتات `scripts/` بنقرة من مالك المشروع |
| تعذر الوصول إلى npm/PyPI/GitHub من بيئة الوكيل | التثبيت والـ Push يتمان على جهاز مالك المشروع |
| Docker Desktop غير مثبت | لا حاويات محلية في هذه المرحلة |
