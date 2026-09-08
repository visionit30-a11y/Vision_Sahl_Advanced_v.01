# Phase 2E — Audit + Security Hardening + Final Security Gates

## الحالة والنطاق

G1 وG2 معتمدتان، وG3 مكتملة محليًا بتاريخ 2026-09-08، من `phase-2d-baseline`:
`1677d114c5736c4032b862ddf0b58517490d1317`.
Migration head: `0015_security_event_wiring`؛ أُثبتت على PostgreSQL معزول فقط.
الفرع المحلي: `codex/phase-2e-security-hardening`.

الأرقام **490 Backend / 225 Frontend في 29 ملفًا / 7 Playwright** تخص baseline المعتمدة،
وليست إعادة تشغيل في G1 أو إثبات اجتياز Phase 2E. لم تنفذ G1 schema/migration أو logging/CI
changes أو dependency install/scan أو تعديلات Authentication/RLS/RBAC/UI Settings.
لم تتغير BRD/SRS. يظل التقريران غير المتتبعين خارج commits.

القرار التفصيلي والكتالوج والحقول والاحتفاظ:
[ADR-0025](adr/ADR-0025-security-audit-and-hardening.md).

## المراجعة المحدودة والفجوات المثبتة

| الموضع الحالي | الموجود أو الفجوة | العمل المقترح لاحقًا |
| --- | --- | --- |
| `app/models/auth_security.py`، `app/auth/controls.py`، migration 0009 | 11 event IDs، writer عام، قيود محدودة للنوع/result | typed catalog وreason/field/link guards دون تعديل migration منشورة |
| `app/db/auth_http.py` ودوال reset | بعض الأحداث مرتبطة بمعاملات أمنية بالفعل | مصفوفة coverage للعمليات القائمة؛ لا إنشاء authentication بديلة |
| `app/core/errors.py` | 500 عامة وinput/ctx masking؛ HTTPException detail وvalidation msg/loc غير مغلقة | safe error/validation projection دون raw input أو استثناء |
| `app/core/logging.py` | masking قبل exception formatting؛ stdlib مسار منفصل | سياسة emission واحدة واختبار stdout/stderr النهائي |
| `app/db/session.py` و`app/core/config.py` | hide_parameters غير مثبت؛ DSN repr يحتاج حجبًا | طبقات DB/config diagnostics محدودة |
| `app/core/middleware.py` | raw path وX-Request-ID في logs؛ cleanup يحتاج finally | route template وinternal correlation وcontext cleanup |
| `tests/test_health.py` | عقد echo لـX-Request-ID موجود | الفصل عن internal audit ID؛ لا تغيير العقد بصمت |
| `.github/workflows/ci.yml` | API/Web/RLS/browser/cleanup موجودة؛ secret guard يغطي .env الجذري فقط | فحص أسرار حقيقي وتبعيات ومخرجات scans |
| CI permissions / action pins | لا permissions صريحة؛ بعض actions على major tags | contents:read، checkout بلا persistence، SHA pins وtimeouts |

لا تعني هذه المراجعة أن الأسرار تسربت فعليًا أو أن dependencies مصابة؛ لم يشغل G1 canary
اختبارًا أو vulnerability scan. إنها فجوات في الضمان والعقد تحتاج إثباتًا في مجموعاتها.

## Security hardening checklist

- كتالوج event/result/reason واحد؛ unknown values ترفض؛ emitter coverage لكل عملية قائمة.
- IDs مثبتة وارتباطات صحيحة؛ لا selector مزور أو raw user input كهوية موثوقة.
- mutation + mandatory event في نفس المعاملة، failure/denial لا تتحول إلى ALLOW.
- append-only runtime، أقل EXECUTE grants، لا schema-wide exemption أو RLS weakening.
- allowlist للحقول؛ لا secrets/credentials/DSN/SQL/headers/bodies أو raw traceback.
- safe AppError وHTTPException وvalidation projection بما يشمل msg/loc/extra-key canaries.
- structlog/stdlib/Uvicorn/SQLAlchemy/config repr مغطاة عند emission النهائي.
- route templates وinternal correlation موثوق وcontext cleanup دائم.
- retention 90 يومًا، purge محدود مع سجل count، واختبارات فقط في DB disposable.
- توثيق حدود DB/proxy/backup التشغيلية؛ لا ادعاء production verification من tests محلية.
- تثبيت scanners وفشلها المغلق؛ لا silent exclusions أو إصلاح تبعيات تلقائي.
- الحفاظ على 401/403/404/409 وno-store وعقود auth/tenant/RBAC/UI Settings الحالية.

## CI security gate plan

تبقى الوظائف الحالية حاجزة، وتضاف البوابات التالية في مجموعة التنفيذ المصرح بها. لا تشغيل
scanners أو تعديل workflow في G1.

| Gate | النطاق وعقد الفشل |
| --- | --- |
| API security regressions | audit atomicity/trusted IDs/retention/redaction + اختبارات Phase 2A–2D الحالية |
| Real server/browser | FastAPI/Uvicorn وPostgreSQL الحقيقيان؛ capture منقح لـstdout/stderr، console/storage/artifacts gates |
| Secret scanning | Gitleaks للتاريخ الكامل وsnapshot المتتبع، مع guard لكل ملفات env/credential المحظورة |
| Python dependencies | تدقيق inventory كاملة من uv.lock تشمل runtime/dev/test/build والـmarkers |
| npm dependencies | npm audit من package-lock، مع dev/optional وعدم إسقاط نطاق بسبب NODE_ENV |
| Scanner integrity | tool/source unavailable، JSON غير صالح، inventory ناقصة أو skip = FAILURE |
| Existing quality gates | Ruff/Mypy/ESLint/TypeScript/Prettier/build وAlembic/RLS/ownership/grants/cleanup |

لا `continue-on-error` أو `|| true` أو تحويل failure إلى warning أو إعادة استخدام تقرير قديم.
لا path filters تسمح بتجاوز الفحص. `--strict-security-gates` القائم يبقى رافضًا skip/xfail/xpass.
تضاف `format:check` إلى CI لأنها موجودة محليًا وليست موصولة حاليًا.
وجود وظيفة في YAML وحده لا يثبت branch protection؛ تحقق required checks على develop/main
جزء من الإغلاق اللاحق، وتغيير إعداد المستودع يحتاج نطاق التفويض المناسب ولا ينفذ في G1.

### تثبيت الأدوات وصلاحيات workflow

- إبقاء Python 3.14 وNode 24 كما هما؛ لا downgrade لتشغيل scanner.
- pin لإصدارات أدوات scanning وتحقق checksum للـbinary، وتثبيت Actions إلى full SHA من المصدر الرسمي.
- `permissions: contents: read` افتراضيًا؛ `persist-credentials: false` لـcheckout، وtimeouts محدودة.
- PR غير موثوق لا يحصل على production secrets؛ لا تشغيل كود PR عبر `pull_request_target`.
- لا interpolation مباشر لـPR title/body/ref داخل shell.
- لا تحميل raw logs/traces/network dumps أو credentials في CI artifacts.
- المصادقة مع GitHub/registry عند الحاجة تستخدم scope تنفيذ مصرحًا به فقط، بلا token في ملفات أو logs.

هذه الخيارات تتفق مع [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use).
لا تغيير لـrepository settings أو اعتماد GitHub محلي في هذه المجموعة.

## Dependency scanning plan

### Python

الأداة المقترحة `pip-audit` كأداة CI/dev فقط؛ الإصدار الدقيق والتوافق الفعلي على Python 3.14
يثبتان في مجموعة CI. لا ندعي توافقًا operational قبل التجربة، ولا نضيف dependency الآن.
`uv.lock` مصدر الحقيقة، ولا يُمرر باعتباره صيغة pylock مدعومة مباشرة من `pip-audit --locked`.

مسار مقترح للتحقق لاحقًا، لا أمر تم تشغيله:
`uv export --locked --all-groups --no-emit-project --format requirements-txt` إلى ملف مؤقت
يحتوي pins/hashes، ثم `pip-audit --strict --require-hashes --disable-pip -r <exported-requirements-file>`.
يلزم إثبات flags للنسخ المثبتة، اكتمال الحصر، عدم إعادة resolution، وعدم إسقاط markers أو extras
المستخدمة. packages التي لا يمكن تدقيقها تفشل البوابة بدل تجاهلها. إذا لم يكف export لحصر target
platforms المعتمدة، يثبت inventory إضافي واضح؛ لا ادعاء فحص Windows من فحص Linux وحده.
كذلك قد لا تدخل تبعيات PEP 517/isolated build، مثل setuptools في build-system الحالي، في
`uv export --all-groups`. يلزم حصرها وقفلها أو إثبات وجودها في inventory المدققة؛ لا نسجل
تغطية build كاملة من مجرد نجاح تصدير runtime/dev groups.

[pip-audit الرسمي](https://github.com/pypa/pip-audit) يوضح locked inputs وخيارات التدقيق،
و[uv export](https://docs.astral.sh/uv/reference/cli/#uv-export) مرجع تصدير القفل.

### npm

`npm audit --json` على package-lock الحالي مع inclusion صريح لـdev/optional والاعتماديات
المستخدمة؛ لا `omit=dev` أو `audit fix`، ولا تحديث package-lock بلا إصلاح معتمد.
الأداة مدمجة؛ لا حاجة مبدئية لإضافة dependency إلى Web. يثبت npm المتوافق مع Node 24 لاحقًا.
التدقيق يبحث في advisories المعروفة؛ لا يثبت خلو كل package من malware.
[npm audit الرسمي](https://docs.npmjs.com/cli/v11/commands/npm-audit/).

### سياسة النتائج والاستثناءات المقترحة

كل advisory غير مستثناة = FAILURE، بغض النظر عن severity أو وجود fix.
تعطل registry/advisory source، audit ناقص، صيغة غير متوقعة، missing/غير متسق lockfile = FAILURE.
لا قائمة تجاهل تلقائية للحالة القديمة.

سجل استثناءات مركزي فارغ مبدئيًا، يحتوي: exact advisory/fingerprint، ecosystem،
package/version أو file/rule، السبب، المالك، مرجع الموافقة، وتاريخ انتهاء بحد أقصى مقترح 30 يومًا.
تغيير النسخة أو انتهاء الاستثناء أو غياب الموافقة يفشل البوابة؛ لا wildcard أو تجاهل tests كلها.
لا استثناء لسر حقيقي؛ fixture اصطناعية قد تحتاج استثناء دقيقًا دون إظهار قيمتها.

[Gitleaks](https://github.com/gitleaks/gitleaks): binary مثبت مع `--redact=100`، لا verbose،
ولا raw report منشور. wrapper يسمح فقط بـrule/advisory ID وموضع آمن وcommit SHA وأعداد.
ملفات وأسماء مكتشفات غير موثوقة تحتاج projection؛ canary tests تثبت عدم خروج secret عبر
stdout/stderr أو Match/context أو report. GitHub masking وحده ليس برهانًا.

## خطة المجموعات والـcommits

كل مجموعة تحتاج موافقة المستخدم قبل تنفيذها؛ الخطة التالية لا تمنح إذنًا بالانتقال التلقائي.

| المجموعة | الناتج وحدودها | تقسيم commits المتوقع |
| --- | --- | --- |
| G1 | ADR/catalog/fields/retention/gates/exit criteria فقط | docs: عقد وكتالوج وخطة المرحلة والقبول والفهرس في commit توثيق ذري واحد |
| G2 | typed audit contracts + writer وDB integrity/append-only guards | domain catalog/validators؛ migration مستقلة بعد 0013 عند الحاجة؛ targeted DB tests |
| G3 | ربط audit بالعمليات الأمنية القائمة + error/logging hardening | atomic emitters؛ HTTP/validation projection؛ logging/DB/config emission guards؛ tests |
| G4 | retention capability وأداة صيانة محدودة وrunbook | صلاحية purge مستقلة إن اعتمدت؛ cleanup وأحداثه؛ disposable DB concurrency/TTL tests |
| G5 | scanners + workflow hardening + negative CI tests | pinned security tools/lock عند الحاجة؛ redacted runners/exceptions؛ CI wiring/docs |
| G6 | full final gates وExit Criteria والإغلاق المحلي | evidence/docs فقط أو إصلاح محدد مثبت؛ أي push/PR/merge/tag يحتاج الطلب المناسب |

G4 لا تبدأ تلقائيًا. لا نجمع تغييرات auth/RBAC/UI business semantics مع audit.
نُفذت 0014 في G2 و0015 في G3 بموافقة المستخدم، دون تعديل migrations السابقة.

### الملفات المتوقع لمسها لاحقًا

- `apps/api/app/models/auth_security.py` و`app/auth/controls.py`؛ عقد audit داخلي typed محدود جديد.
- `apps/api/app/db/auth_http.py` والخدمات/الدوال القائمة التي تصدر حدثًا أمنيًا فقط.
- حدود الخدمات الحالية في auth وauthorization/role administration لغرض audit فقط؛ لا decisions جديدة.
- `apps/api/app/core/{errors,logging,middleware,context,config}.py` و`app/db/session.py`.
- migration مستقلة في `migrations/versions/` واختبارات catalog/ownership/grants/atomicity/retention.
- اختبارات errors/password/auth transport وtests جديدة للـreal server emission؛ browser gate الحالية.
- `.github/workflows/ci.yml`، runners محدودة في `.github/ci/`،
  `.gitleaks.toml` و`.github/security-exceptions.json` مقترحتان.
- `apps/api/pyproject.toml` و`apps/api/uv.lock` فقط إذا أضيفت أداة scanning لمجموعة dev/security.
- `docs/dependencies.md` ووثائق Phase 2E وrunbook محدود؛ لا BRD/SRS.

## القرارات التي ينتظرها التنفيذ

اعتماد G1 يشمل اقتراح: retention للأحداث 90 يومًا، نهج الحقول المغلق والكتالوج، ورفض كل advisory
غير مستثناة مع استثناء دقيق مدته القصوى 30 يومًا، واختيار Gitleaks/pip-audit/npm audit.
لا يوجد blocker يمنع توثيق G1. migration 0014 معتمدة ومنفذة في G2؛ صلاحية maintenance مؤجلة إلى G4؛
مدة/آلية backup الفعلية وrequired branch checks وإصدارات scanners المقبولة تثبت في مجموعاتها،
ولا تسجل PASS الآن أو تتحول إلى claim بأن production خالية من مخاطر غير مفحوصة.

## تحقق G1

التحقق في G1 يقتصر على مراجعة اتساق الوثائق والروابط المحلية وdiff/whitespace ونطاق الملفات.
لم تُشغّل الاختبارات المحلية أو scanners، ولم يحصل push/PR أو تعديل إعداد GitHub.

## G2 — الإغلاق المحلي

اعتمد المستخدم صراحة migration `0014_security_audit_contract` وتقوية schema/functions/triggers
واختبارها على PostgreSQL معزول. اكتملت typed contracts والـwriter وربط نقاط audit القائمة فقط،
والقيود/المنح واختبارات الذرية والعلاقات وحفظ التاريخ.

**313 اختبارًا مستهدفًا PASS**: 97 domain/writer + 42 PostgreSQL audit + 174 حارس regression.
Ruff وMypy وAlembic check و0014 → 0013 → 0014 وRLS/ownership/cleanup PASS.
النتائج وتوقيعات الدوال وحدود الإثبات في [تقرير G2](phase-2e-g2-verification.md).

### حد أحداث إدارة الأدوار

policy على `auth.roles` تخص sahl_app، وFORCE RLS تمنع migrator من قراءة rows عبر SECURITY
DEFINER. لذلك تبقى أحداث roles السبعة وحدث retention معرّفة في العقد ومرفوضة للكتابة في G2.
لا BYPASSRLS ولا policy جديدة ولا قبول UUID مجرد. يلزم تثبيت طريقة إثبات متوافقة قبل ربط
role emitters في G3. هذا حد معلن للمجموعة وليس إثباتًا مكتملًا لأحداث إدارة الأدوار.

هذا وصف حد G2 التاريخي. حُلّ ربط أحداث الأدوار في G3 بإثبات التغيير الفعلي داخل المعاملة،
كما في القسم التالي، دون تغيير policies أو FORCE RLS.


## G3 — الإغلاق المحلي

اكتمل ربط أحداث المصادقة والجلسات وكلمات المرور والرفض وإدارة الأدوار، مع تقوية error/validation
وstdout/stderr وSQLAlchemy/config redaction. وافق المستخدم على تنسيق login/password change
الداخلي وعلى الدوال الأربع المحددة في migration 0015؛ لا HTTP endpoints جديدة.

أحداث الأدوار تستخدم private transaction proof + row triggers على التغيير الفعلي تحت RLS؛
الـwriter يستهلك الإثبات في معاملة التغيير نفسها. deferred guard يمنع commit عند فقد الحدث.
الجدول الخاص ليس مصدر صلاحية ولا يمنح وصولًا عامًا إلى RBAC؛ لا runtime/PUBLIC table grants.

**717 Backend tests PASS** مع `--strict-security-gates`، تتضمن **88 اختبارًا جديدًا** في G3.
Ruff وMypy وAlembic check و0015 → 0014 → 0015 وRLS/ownership/cleanup PASS.
اختبار real Uvicorn على 8011 أثبت تنقيح stdout/stderr بعد الاستثناء؛ هذا منفذ اختبار مؤقت،
ولا يغير Local Backend8010 أو Frontend5173 أو Browser Test5187.
PostgreSQL17 المعزول على5434 أُوقف وحُذفت بياناته بعد حفظ الأدلة المنقحة.

التفاصيل والمصفوفة وحدود الادعاء في [تقرير G3](phase-2e-g3-verification.md).
G4 لم تبدأ؛ تبقى retention capability/purge/runbook خارج هذا التنفيذ، وCI/scanners في G5،
والبوابات النهائية الشاملة للمرحلة في G6. لا push/PR أو CI جديدة في G3.
