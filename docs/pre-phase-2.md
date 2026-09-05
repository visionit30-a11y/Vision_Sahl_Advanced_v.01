# الأساس الهندسي قبل Phase 2 — وثيقة القبول

مرحلة قصيرة بين إغلاق **Phase 1B** وبدء **Phase 2A**، غرضها واحد: ألا تُبنى النمذجة
متعددة الجهات فوق أرضية غير محسومة. لم يُضَف فيها أي سلوك منتج — لا جدول، ولا سياسة عزل،
ولا واجهة برمجية.

## 1. الفجوات الخمس التي أُغلقت

| # | الفجوة | ما كانت عليه | ما صارت إليه |
|---|---|---|---|
| A | تحذير إهمال في Starlette | `HTTP_422_UNPROCESSABLE_ENTITY` يطلق `StarletteDeprecationWarning` عند الاستيراد | `HTTP_422_UNPROCESSABLE_CONTENT` في `app/core/errors.py`، مع اختبار انحدار يرفض أي تحذير إهمال من Starlette |
| B | خط أساس Node | الجهاز 24.14.1 وCI يبني على 20 (منتهي الدعم) | **Node 24** مصدرًا واحدًا في `apps/web/.nvmrc`، يقرؤه CI و`engines` و`00-check.ps1` |
| C | خط أساس Python | الجهاز 3.13.1 · CI 3.12 · `requires-python >=3.12` مفتوح | **Python 3.14** مصدرًا واحدًا في `apps/api/.python-version`، ونطاق مغلق `>=3.14,<3.15` |
| D | قفل تبعيات الخلفية | الواجهة مقفلة والخلفية بلا قفل | `apps/api/uv.lock` في Git · `uv sync --frozen` · `uv lock --check` بوابة حاجزة — ADR-0013 |
| E | قاعدة بيانات في CI | `pytest` بلا قاعدة، ودورة Alembic تُتخطّى | PostgreSQL 17 حقيقي بفحص صحة · دوران منفصلان · تحقق ملزم من صلاحيات `sahl_app` · دورة مهاجرات كاملة |

## 2. عيبان اكتُشفا أثناء التنفيذ وأُغلقا

**دورة حياة البيئة الافتراضية.** فشلت إعادة بناء `apps\api\.venv` مرتين برسالة
`Access to the path '_greenlet.cp313-win_amd64.pyd' is denied` ثم `'_rust_notify...'`.
السبب: شجرة `uvicorn --reload` من تشغيل سابق كانت لا تزال حية — المشرف يحمل `watchfiles`
والعامل يحمل `greenlet` — وويندوز يقفل الوحدة المحمَّلة. وكان الحذف يجري **بلا أي خطوة
دورة حياة**، فحذف `site-packages` تحت عامل حي، فأعاد المراقب توليده مرارًا وكل مرة يفشل
استيراده.

الإصلاح يثبت الملكية من البيئة نفسها: `Get-ProcessesUsingPath` تُرجع العمليات التي مسارها
التنفيذي داخل المجلد أو سطر أوامرها يذكره، و`Stop-ProcessesUsingPath` توقف تلك وحدها —
**لا مطابقة بالاسم إطلاقًا** — و`Remove-ProjectDirectory` تؤكد المسار ثم تعيد المحاولة
بعدد محدود وتفشل مغلقةً مسمّيةً الملف المقفول، بلا إعادة تسمية ولا حذف مؤجل.

**قراءة إصدار البيئة.** بعد نجاح البناء رفض السكربت عمله نفسه:
`The rebuilt virtual environment runs  but the baseline is 3.14`. السبب أن `pyvenv.cfg`
ليس له شكل واحد: وحدة `venv` تكتب `version` بينما **uv تكتب `version_info`**، والقارئ كان
يطابق `^version\s*=` فلا يطابق شيئًا ويعيد فراغًا صامتًا. والنمط الضيق نفسه كان مكرَّرًا في
ثلاثة مواضع، وأخطرها موضع **قرار إعادة البناء**: كان سيقرأ بيئة 3.14.7 السليمة فراغًا
ويحذفها.

صار القارئ واحدًا مشتركًا من مصدرين مستقلين — المفسّر نفسه (`python.exe --version`) و
`pyvenv.cfg` بالمفتاحين معًا — يقارنان على `Major.Minor`، ولا يُجيز الحذف إلا اتفاقهما.
تعارضهما = **FAIL CLOSED** بلا حذف. ويغطي الانحدار
`apps/api/tests/test_environment_baseline_contract.py`.

## 3. PRE-PHASE-2-BASELINE-GATE — نتيجة التحقق

المصدر: `_logs/03-test-20260906-002357.log` و`_logs/01-setup-20260906-002249.log`.

| # | الشرط | النتيجة |
|---|---|---|
| 1 | `uv lock --check` | PASS — 47 حزمة |
| 2 | خط أساس Python | 3.14 |
| 3 | البيئة الفعلية | 3.14.7 (المفسّر و`version_info` متطابقان) |
| 4 | خط أساس Node | 24 (المثبت 24.14.1) |
| 5 | `StarletteDeprecationWarning` | صفر في السجل كله |
| 6 | اختبارات الخلفية | 23 PASS |
| 7 | اختبارات الواجهة | 213 PASS في 28 ملفًا |
| 8 | Ruff (lint) | PASS |
| 9 | Ruff (format check) | PASS — 28 ملفًا |
| 10 | mypy | PASS — 27 ملفًا |
| 11 | ESLint | PASS |
| 12 | TypeScript | PASS |
| 13 | بناء الإنتاج | PASS |
| 14 | Alembic downgrade → upgrade → current | PASS — `0001_baseline (head)` |
| 15 | Prettier | PASS |
| 16 | لا SKIP في بوابة ملزمة | صفر SKIP في السجل |
| 17 | لا انحدار في Phase 1 | 213 اختبار واجهة دون تغيير في العدد أو الملفات |

**النتيجة: PASS محليًا.**

## 4. مستويات القبول الثلاثة

نجاح `03-test` محليًا **لا يثبت** نجاح GitHub Actions، فالأول يعمل على ويندوز والثاني على
Ubuntu. لذلك فُصل القبول ثلاثة مستويات، **وكلها متحققة الآن**:

| المستوى | الحالة | الدليل |
|---|---|---|
| **A — خط الأساس المحلي** | ✅ VERIFIED | `_logs/03-test-20260906-002357.log` — ١١ بوابة PASS |
| **B — إعداد CI** | ✅ VERIFIED | قراءة `.github/workflows/ci.yml` و`.github/ci/setup-database.sql` |
| **C — تنفيذ CI** | ✅ VERIFIED | **PR #6** على GitHub Actions — الوظائف الثلاث خضراء |

## 5. تنفيذ CI — ما أثبتته المنصة فعليًا

المصدر: تشغيل GitHub Actions على **PR #6** (`chore/pre-phase-2-engineering-baseline → develop`)،
مراجَع بصريًا من مالك المشروع.

| الوظيفة | النتيجة |
|---|---|
| `API (lint, types, tests, database)` | ✅ PASS |
| `Web (lint, types, tests, build)` | ✅ PASS |
| `No committed secrets` | ✅ PASS |

وخطوات وظيفة API كلها خضراء بالترتيب:

| الخطوة | ما أثبتته |
|---|---|
| Set up job | حُلّت كل الـActions، ومنها `astral-sh/setup-uv` **بالـSHA المثبت** |
| Initialize containers | **PostgreSQL 17 حقيقي شُغِّل فعلًا** داخل GitHub Actions واجتاز فحص الصحة — لم يعد افتراضًا مقروءًا من ملف |
| `actions/checkout` · `actions/setup-python` | Python **3.14** من `apps/api/.python-version` |
| `astral-sh/setup-uv` | مثبَّت على `c771a70e…` ‏(v9.0.0)، وأداة uv على `0.12.10` |
| Dependency lock is consistent | `uv lock --check` — **`uv.lock` استُعمل فعليًا داخل CI** ولم يُتخطَّ |
| Install from the lock | `uv sync --frozen` — التثبيت من القفل حصرًا، بلا حلّ جديد |
| Ruff · Mypy | بوابتا الجودة على الشجرة نفسها التي يركّبها القفل |
| Create the migration and application roles | `sahl_migrator` مالك المخطط · `sahl_app` لا يملك شيئًا |
| **The application role cannot bypass isolation** | ✅ `sahl_app` ليس `SUPERUSER` ولا `BYPASSRLS` — **البوابة الأمنية الحاكمة لـPhase 2A نجحت على قاعدة حقيقية** |
| **Alembic migration round trip** | ✅ `upgrade → downgrade base → upgrade → current` مع تأكيد `(head)` على PostgreSQL 17 الحقيقي |
| Pytest | مجموعة الخلفية تحت `APP_ENV=test` مقابل قاعدة حقيقية |
| Stop containers · Complete job | إنهاء نظيف |

**لا SKIP ولا `continue-on-error` في أي خطوة.**

## 6. الأثر على Phase 2A

أهم ما أثبته هذا التشغيل ليس اخضرار الوظائف، بل أن **بوابة العزل صارت قابلة للإثبات آليًا**.
سياسات RLS التي تُكتب في Phase 2A لا يمكن التحقق منها إلا على PostgreSQL حقيقي وبدور
لا يستطيع تجاوزها؛ ولو كانت الهجرات والتطبيق يتقاسمان دورًا واحدًا لمرّت كل سياسة عزل
**خاملة** ونجحت اختباراتها للسبب الخطأ. هذا الخطر أُغلق قبل كتابة أول سطر من Phase 2A،
وهو سبب وجود هذه المرحلة كلها.

**الأساس الهندسي مغلق: PRE-PHASE-2-BASELINE-GATE = PASS.**
