# منصة سهل المطور — Sahl Developer Platform

منصة سحابية عربية أولًا ومتعددة الجهات (Multi-Tenant SaaS) للقطاع غير الربحي في المملكة
العربية السعودية. المالك: **شركة رؤى الحلول لتقنية المعلومات**.

> **المرجع الملزم:** وثيقتا `BRD-SAHEL-001` و`SRS-SAHEL-001` في جذر المشروع. عند أي تعارض بين
> الكود والوثيقتين، الوثيقتان هما المرجع الأعلى. راجع `docs/README.md`.

## الحالة

**Phase 0 — Repository & Local Foundation.** لا يوجد منطق أعمال في هذا الإصدار؛ الغرض تأسيس
مستودع وبيئة تشغيل قابلة للتشغيل والاختبار. التفاصيل في `docs/phase-0.md`.

## التقنية المعتمدة

| الطبقة | التقنية |
|---|---|
| الواجهة | React + Vite + TypeScript |
| الخلفية | FastAPI (Python) |
| قاعدة البيانات | PostgreSQL |
| عزل الجهات | PostgreSQL Row-Level Security — من Phase 2 |
| الذاكرة المؤقتة والصفوف | Redis |
| المستندات | Object Storage |
| الاستضافة | Oracle Cloud Infrastructure + OKE |
| المعمارية | Modular Monolith |

**ممنوع:** Tailwind CSS · Bootstrap · أي إطار CSS بديل · Node.js كخلفية أو API أو Jobs ·
استبدال أي طبقة من الجدول أعلاه.

## بنية المستودع

```
apps/api/        خلفية FastAPI  (app/core, app/db, app/cache, app/api, app/services, app/modules)
apps/web/        واجهة React + Vite + TypeScript
migrations/      مهاجرات Alembic المتسلسلة
infra/terraform/ بنية OCI التحتية — Phase 11
docs/            فهرس الوثائق وسجل قرارات المعمارية (ADR)
scripts/         سكربتات التشغيل على Windows / PowerShell
tests/           اختبارات التكامل العابرة للطبقات — من Phase 2
_logs/           سجلات التشغيل المحلية (خارج Git)
```

## التشغيل المحلي (Windows + PowerShell)

المتطلبات: Git · Node.js · Python 3.12 أو أحدث · PostgreSQL.

شغّل السكربتات بـ **زر يمين ← Run with PowerShell** بالترتيب:

```powershell
scripts\00-check.ps1    # تقرير عن البيئة — لا يغيّر شيئًا
scripts\01-setup.ps1    # تهيئة البيئة والحزم وقاعدة البيانات والمهاجرات
scripts\02-run.ps1      # تشغيل الخلفية والواجهة
scripts\03-test.ps1     # تشغيل بوابات الجودة كاملة
scripts\05-stop.ps1     # إيقاف الخدمات
```

بعد `02-run.ps1` افتح: **http://localhost:5173**

كل سكربت يكتب سجلًا كاملًا في `_logs\`. التفاصيل وضمانات السلامة في `scripts/README.md`.

## نقاط الفحص الصحي

| النقطة | المعنى |
|---|---|
| `GET /health` | حياة التطبيق — لا تعتمد على أي خدمة خارجية |
| `GET /health/db` | فحص PostgreSQL — `503` عند التعذر |
| `GET /health/redis` | فحص Redis — `disabled` حالة إعداد معلنة وليست نجاحًا مزيفًا |

Redis تبقى التقنية المعتمدة، وتشغيلها الفعلي مؤجل إلى Phase 3 بقرار موثق في
`docs/adr/ADR-0003-redis-deferred-verification.md`.

## Git

`main` مستقر (دمج عبر Pull Request فقط) · `develop` للتكامل · `feature/*` لكل مهمة.
الأسرار لا تُودَع في Git إطلاقًا؛ استخدم `.env` المحلي المبني على `.env.example`.

## عبر المنصات

بيئة التطوير المحلية Windows، لكن الـ Runtime نفسه غير مرتبط بويندوز: المسارات عبر مكتبات
المنصة، والإعدادات عبر متغيرات البيئة، والنشر عبر الحاويات.
