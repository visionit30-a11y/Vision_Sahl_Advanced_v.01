# Phase 2E — Exit Criteria

**الحالة:** مراجعة G6 بتاريخ 2026-09-08؛ الأدلة المحلية معتمدة، وGitHub required checks وCI النهائي قيد الإغلاق.
**الأساس:** `phase-2d-baseline` — `1677d114c5736c4032b862ddf0b58517490d1317`.
**Migration الحالية:** `0016_security_audit_retention`؛ أُثبتت على PostgreSQL معزول.

المرجع: [ADR-0025](adr/ADR-0025-security-audit-and-hardening.md) و[خطة Phase 2E](phase-2e.md).

## مصفوفة القبول النهائي

| # | معيار القبول | الإثبات المطلوب لاحقًا | الحالة المرحلية |
| --- | --- | --- | --- |
| 1 | كتالوج event/result/reason مركزي typed وثابت | unknown/duplicate/mapping tests وDB catalog equality | PASS — G2 |
| 2 | اكتمال emitters للعمليات الأمنية القائمة | coverage لكل حدث، بلا endpoints مصطنعة أو auth redesign | PASS — G3 |
| 3 | IDs وروابط موثوقة فقط | forged user/session/membership/role IDs وcross-tenant denial | PASS — G3 |
| 4 | حصر الحقول ومنع الأسرار | canaries لـpassword/PHC/bearer/reset/CSRF/keys/DSNs، ورفض raw metadata | PASS — G3 |
| 5 | تغيير الحالة والحدث ذريّان | فشل event يلغي mutation؛ retry/no-op لا يخلق نجاحًا مضللًا | PASS — G2–G4 |
| 6 | failure/denial لا تختفي بصمت أو تفتح الوصول | rollback + bounded audit transaction، DB outage يبقى DENY | PASS — G3 |
| 7 | runtime append-only وأقل grants | لا direct SELECT/INSERT/UPDATE/DELETE/TRUNCATE أو ownership؛ exact function guards | PASS — G2–G4 |
| 8 | تصنيف DB والعزل ثابتان | auth exception محددة، جميع tenant RLS/FORCE/USING/WITH CHECK guards | PASS — G2/G3 |
| 9 | error envelopes منقحة ومتوافقة | AppError/HTTPException/500، 401/403/404/409، no-store | PASS — G3 |
| 10 | validation لا يعيد input حساسًا | body/query/path/header، msg/loc/extra keys/malformed JSON canaries | PASS — G3 |
| 11 | logging آمن عند الإخراج النهائي | structlog/stdlib/Uvicorn + exception chains عبر real server stdout/stderr | PASS — G3 |
| 12 | SQLAlchemy/driver/config لا يكشف أسرارًا | hide_parameters/echo/DSN repr guards وDB failure canaries | PASS — G3 |
| 13 | metadata وcontext آمنان | route template، internal correlation، request-ID compatibility وfinally/concurrency | PASS — G3 |
| 14 | retention وpurge محدودتان | cutoff وTTL وbatches والتزامن وrollback event failure في DB disposable | PASS — G4 |
| 15 | حدود التشغيل والنسخ موثقة ومثبتة بقدر البيئة | maintenance grants، DB/proxy log settings، restore/backup retention واعتماد التشغيل | PASS — G6، حدود البيئة موثقة؛ لا ادعاء production |
| 16 | لا أسرار في تاريخ Git أو snapshot المتتبع | Gitleaks + nested env guards + redacted scanner output tests | PASS — G5 |
| 17 | تبعيات Python/npm مدققة بالكامل | frozen inventories، markers/dev/optional coverage، كل advisory بلا استثناء تفشل | PASS — G5 |
| 18 | scanners fail closed والاستثناءات ضيقة | outage/invalid output/missing lock/skip ورفض كل استثناء غير معتمد | PASS — G5 |
| 19 | CI أقل صلاحيات وبوابات حاجزة فعلًا | SHA pins/timeouts/contents:read، required checks verified للنطاق المصرح | PARTIAL — G5 |
| 20 | browser proof وعدم تغير Design System | Playwright حقيقي: 5187 → FastAPI8010 → PostgreSQL، لا secrets storage/console/artifacts | PASS — G5 |
| 21 | regressions وكامل quality/database gates | Backend/Frontend كاملة، Ruff/Mypy/ESLint/TS/Prettier/build، Alembic/round-trip/RLS/cleanup | PASS — G5 |
| 22 | scope/history/evidence سليمة | لا Business Modules/Phase3، لا auth/RBAC/UI/RLS redesign؛ تقريران مستثنيان وBRD/SRS ثابتتان؛ CI لكل SHA مطلوب عند الإغلاق | PARTIAL — G5 |

**النتيجة الحالية:** 20 معيارًا PASS و2 قيد الإثبات الخارجي (#19 و#22)؛ لم تكتمل موافقة PR بعد.

دليل G5: **996 Backend PASS /225 Frontend PASS (29files) /7 Playwright PASS**، بلا SKIP/XFAIL.
Gitleaks على453 ملفًا متتبعًا والتاريخ/merge diffs و26 text artifacts PASS؛ pip-audit على50
project +1 build +28 scanner، وnpm على350 nodes بلاadvisories.
Ruff/Mypy/ESLint/TypeScript/Prettier/build/Alembic/head→base→head/RLS/ownership/cleanup
وG4 retention PASS. [التفاصيل](phase-2e-g5-verification.md).

- معيار15 PASS ضمن البيئة المصرح بها: capability/runner/DB logs المعزولة مثبتة، وحدود production proxy/backup/job وخطوات الاعتماد قبل النشر موثقة في تقرير G6. هذا لا يثبت إعدادات production أو سياسة النسخ الفعلية.
- معيار19 جزئي: workflow/scanner contracts مثبتة محليًا؛ GitHub run وربط required checks
  بالـSHA الفعلي يُثبتان في الإغلاق المصرح لاحقًا. لا تعديل لإعدادات GitHub هنا.
- معيار22 جزئي: النطاق والتقريرين المستثنيين وملفات المنتج ثابتة في G5؛ مراجعة المرحلة وCI/PR
  النهائيان ينتظران G6. لا push أوmerge أوtag أوPhase3.

دليل G4 التاريخي404 targeted PASS؛ دليل G3 التاريخي717 Backend PASS؛ دليل G2 التاريخي313 targeted
PASS. لا تُجمع هذه الأعداد على996 لأنها داخلة في regression suite.

## قواعد تنفيذ الإثبات لاحقًا

- اختبارات domain/service/HTTP/DB targeted في المجموعة الخاصة بها، وكامل البوابات في G6.
- real Uvicorn لا ASGITransport وحده لإثبات exception logging؛ real PostgreSQL لذرية الأحداث والمنح.
- لا SKIP أو xfail/xpass في security gates، ولا fake browser أو mock DB بديل لإثبات العزل.
- canaries اصطناعية تولّد أثناء التشغيل؛ لا تقارير تحفظ سرًا حقيقيًا أو stdout خامًا.
- migrations والـpurge على disposable DB فقط؛ لا downgrade/delete بيانات development لإثبات النجاح.
- تستمر قيود المنافذ: Local Frontend5173 وBackend8010، Browser Test5187 فقط، بلا fallback أو
  إيقاف عملية غير مثبتة الملكية؛ port8000 خارج المشروع.
- تحفظ الأدلة المنقحة فقط، ويرتبط تقرير CI بالـSHA والفرع والحدث الفعلي؛ source/PR/merge مستقلة.
- يبقى اعتماد production retention/backup/log sink configuration صريحًا؛ لا يمكن لاختبار محلي
  أن يثبت سياسة نسخ أو إعداد proxy لم تتم مراجعتهما.

## مراجعة G6

راجع [تقرير الإغلاق](phase-2e-g6-verification.md) لأدلة كل مجموعة وحدود التشغيل وحالة GitHub الفعلية.
