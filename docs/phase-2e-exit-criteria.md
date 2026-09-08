# Phase 2E — Exit Criteria

**الحالة:** إثبات G4 المحلي بتاريخ 2026-09-08؛ بقية معايير المرحلة تنتظر مجموعاتها.
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
| 15 | حدود التشغيل والنسخ موثقة ومثبتة بقدر البيئة | maintenance grants، DB/proxy log settings، restore/backup retention واعتماد التشغيل | PARTIAL — G4 |
| 16 | لا أسرار في تاريخ Git أو snapshot المتتبع | Gitleaks + nested env guards + redacted scanner output tests | PLANNED |
| 17 | تبعيات Python/npm مدققة بالكامل | frozen inventories، markers/dev/optional coverage، كل advisory بلا استثناء تفشل | PLANNED |
| 18 | scanners fail closed والاستثناءات ضيقة | outage/invalid output/missing lock/skip/expired exception negative tests | PLANNED |
| 19 | CI أقل صلاحيات وبوابات حاجزة فعلًا | SHA pins/timeouts/contents:read، required checks verified للنطاق المصرح | PLANNED |
| 20 | browser proof وعدم تغير Design System | Playwright حقيقي: 5187 → FastAPI8010 → PostgreSQL، لا secrets storage/console/artifacts | PLANNED |
| 21 | regressions وكامل quality/database gates | Backend/Frontend كاملة، Ruff/Mypy/ESLint/TS/Prettier/build، Alembic/round-trip/RLS/cleanup | PARTIAL — G4 |
| 22 | scope/history/evidence سليمة | لا Business Modules/Phase3، لا auth/RBAC/UI/RLS redesign؛ تقريران مستثنيان وBRD/SRS ثابتتان؛ CI لكل SHA مطلوب عند الإغلاق | PARTIAL — G4 |

**النتيجة الحالية:** 14 معيارًا مثبتًا محليًا، و3 جزئية، و5 مخططة؛ Phase 2E لم تُغلق.
دليل G4: **404 targeted tests PASS**، منها112 جديدة و292 regression؛ migration0016 وRuff/Mypy/
Alembic/round-trip/RLS/cleanup PASS. [التفاصيل](phase-2e-g4-retention.md).
دليل G3 التاريخي: **717 Backend tests PASS**، منها88 جديدة.
دليل G2 التاريخي: **313 targeted tests PASS**. التفاصيل في [تقرير G3](phase-2e-g3-verification.md).
معيار15 جزئي: capability والـrunner وDB/Uvicorn المعزول مثبتة؛ production proxy/backup/job غير منفذة.
معيار21 جزئي: G4 وحراس DB المرتبطة مثبتة؛ لم تُعد Full Backend/Frontend/Playwright في G4.
معيار 22 جزئي: النطاق وGit محليًا مثبتان؛ CI والإغلاق النهائي للمرحلة مؤجلان.
لا نتائج scanners أو GitHub CI جديدة؛ تعديل provisioning الاختباري في G4 لا يثبت تشغيل CI.
النتيجة ليست22/22 PASS؛ G5 لم تبدأ.

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
