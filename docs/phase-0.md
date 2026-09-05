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

| # | المعيار | الدليل | الحالة |
|---|---|---|---|
| 1 | فروع `main` / `develop` / `feature/phase-0-foundation` والمستودع الرسمي مربوط | `git branch` · `origin` مضبوط | ✅ |
| 2 | لا أسرار ولا `.env` في تاريخ Git | فحص `git ls-files` وبحث أنماط الأسرار | ✅ |
| 3 | الخلفية تعمل و`/health` يستجيب | `200 {"status":"ok","name":"Sahl Developer Platform","version":"0.1.0","environment":"development"}` | ✅ |
| 4 | `/health/db` يستجيب `up` | `200 {"dependency":"postgresql","status":"up","detail":null}` | ✅ |
| 5 | `/health/redis` يعلن `disabled` دون ادعاء نجاح | `200 {"dependency":"redis","status":"disabled","detail":"Redis is not enabled in this environment (see ADR-0003)."}` | ✅ |
| 6 | الواجهة تعمل وتقرأ حالة الخلفية | `http://localhost:5173` — مراجعة مالك المشروع في المتصفح | ✅ |
| 7 | Alembic يطبّق مهاجرة الأساس **ويتراجع عنها** | `downgrade 0001_baseline -> ` ثم `upgrade -> 0001_baseline` ثم `0001_baseline (head)` | ✅ |
| 8 | دور التطبيق بلا `SUPERUSER` وبلا `BYPASSRLS` | `sahl_app · is_superuser = f · bypasses_rls = f` | ✅ |
| 9 | `ruff` + `mypy` + `pytest` بلا أخطاء | ruff PASS · mypy PASS · pytest **13 passed** | ✅ |
| 10 | `eslint` + `tsc --noEmit` + `vitest` + `build` بلا أخطاء | eslint PASS · tsc PASS · vitest **3 passed** · build PASS | ✅ |
| 11 | لا منطق أعمال ولا جدول مجال ولا شاشة أعمال | مراجعة شجرة الملفات | ✅ |
| 12 | Commits ذرّية وتقرير تغيير واضح | تاريخ الفرع | ✅ |

### معايير إضافية أُثبتت في هذه المرحلة

| المعيار | الدليل | الحالة |
|---|---|---|
| خادم PostgreSQL مستقل عن Odoo، متحقَّق منه بـ `data_directory` لا بالافتراض | `C:/Program Files/PostgreSQL/17/data` — PostgreSQL 17.11 على المنفذ 5433 | ✅ |
| فحوص التنسيق | `ruff format --check` PASS · `prettier --check` PASS | ✅ |

**معيار مُستثنى بقرار موثق:** تشغيل Redis محليًا (ADR-0003) — مؤجل إلى Phase 3، ولا يمنع
إغلاق Phase 0. ونقطة `/health/redis` تعلن الحالة `disabled` صراحة بدل ادعاء النجاح.

## قيود بيئة موثقة

| القيد | الأثر |
|---|---|
| تعذر تنفيذ أوامر على ويندوز من الوكيل | التشغيل والاختبار عبر سكربتات `scripts/` بنقرة من مالك المشروع |
| تعذر الوصول إلى npm/PyPI/GitHub من بيئة الوكيل | التثبيت والـ Push يتمان على جهاز مالك المشروع |
| Docker Desktop غير مثبت | لا حاويات محلية في هذه المرحلة |
