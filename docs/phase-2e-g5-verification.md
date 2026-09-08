# Phase 2E — G5: blocking security gates

تاريخ الإثبات: 2026-09-08. الفرع: `codex/phase-2e-security-hardening`.
Migration ثابتة: `0016_security_audit_retention`.

## النطاق

G5 تخص CI/scanners/tests/docs فقط. لا تعديل لكود Authentication أوRBAC أوRLS أوUI Settings
أوretention أوDesign System. لا Business Modules أوPhase3 أوSIEM أوproduction deployment.

صُحح حارس مصدر سابق لتصنيف `create_engine` داخل الملف المعتمد
`app/maintenance/security_audit_retention.py` فقط. بقية constructors وimports ممنوعة،
ولا استثناء شامل لمجلد maintenance.20 حارسًا إضافيًا تمنع وصول الخدمات إلى أداة الصيانة.
لم تتغير أداة G4 أو capability أوgrants أوRLS.

## الأدوات والتغطية

| الأداة | النسخة | التثبيت والحصر |
| --- | --- | --- |
| Gitleaks | 8.30.1 | archive رسمي Windows/Linux x64 معSHA256 ثابت، والتحقق من archive والبinary قبل الاستخدام |
| pip-audit | 2.10.1 | بيئة منفصلة؛28 حزمة مقفلة بالنسخ وhashes فيpip-audit.lock.txt |
| npm audit | 11.11.0 | archive رسمي لـnpm معSHA512 ثابت؛ يعمل علىNode24 خارج المشروع |
| uv | 0.12.10 | النسخة الحالية؛ frozen export/sync |
| Python / PostgreSQL | 3.14 /17 | دون تغيير baseline |
| setuptools | 84.0.0 | النسخة الموجودة فيcache قبلG5؛ قفل build مستقل ومدقق |

ملفات `uv.lock` و`package-lock.json` و`pyproject.toml` و`package.json` لم تتغير.
أدوات الفحص لا تدخل بيئة تشغيل المنتج.

Python: تصدير `pylock.toml` باستخدام `uv export --frozen --all-groups --all-extras
--no-emit-project --format pylock.toml`. تطابق البوابة جميعname/version معuv.lock ونتيجة
pip-audit. PyLockSource يفحص جميعmarkers المسجلة، ومنها منصات أخرى؛ لاrequirements export
يسقط حزمًا حسب منصة الجهاز. تُفحص أيضًا تبعية build وبيئة scanner الفعلية.

قيد build يستخدم `uv sync --frozen --config-file ../../.github/ci/uv-build.toml` منapps/api.
الإعداد الصحيح هو `[extra-build-dependencies]` مع `sahl-api = ["setuptools==84.0.0"]`.
حقلbuild-constraint-dependencies الخارجي لا يطبقهuv sync0.12.10، لذلك لا يُستخدم.
أُثبتت بيئة/cache جديدتان مع84.0.0، واختبارpin مستحيل فشل بتعارض صريح؛ ثبت تطبيق القيد فعليًا.

npm: نسخة مؤقتة منpackage.json/package-lock.json، بلاnpmrc أوcredentials محلية؛
`npm audit --json --package-lock-only --include=dev --include=optional --include=peer
--audit-level=low --registry=https://registry.npmjs.org`. تُطابقmetadata/nodes معالقفل.
لاupgrade أوaudit fix. تُقارنhashes ملفّي القفل قبل/بعد حتى عند الفشل.

## الفشل والأسرار

- كلadvisory، بكلseverity، تفشل البوابة. لا إصلاح dependency تلقائي؛ يلزم اعتماد المالك.
- outage/timeout/malformed JSON/incomplete inventory/skip/version أوchecksum غير صحيح = FAIL.
- لاcontinue-on-error أوsoft-pass. سجلsecurity-exceptions فارغ، وأي إدخال غير معتمد مرفوض.
- Gitleaks يفحص التاريخ الكامل وmerge-only patches عبر`--all --full-history -m`، وsnapshot
  للملفات المتتبعة الحالية. يرفضshallow clone وcredential/env paths المتداخلة وignore files.
  `.env.example` مسموح بالاسم فقط ويظل محتواه مفحوصًا.
- stdout/stderr تُلتقط وتُفحص فيmemory دون حفظها أوإعادة طباعتها. scanner reports أيضًا فيmemory.
  النتيجة المحفوظة حقول ثابتة وأعداد فقط؛ لاMatch/context أوexception messages خام.
- تُمنعcredentials التطبيق/GitHub من الوصول إلىscanner subprocesses؛ سجلاتnpm مؤقتة بلاsecrets.
- artifacts المعتمدة: summaries، وbuild النصيJS/CSS/HTML/JSON/map/text، وPlaywright
  `.last-run.json` فقط. لاraw logs أوtrace/video/screenshot/network dumps أوuploads.
  Fonts/images/binary خارج ادعاء فحص النص.
- الجذور الوحيدة: `_logs/security-artifacts` محليًا و`RUNNER_TEMP/security-logs` فيCI.
  Symlink/junction/empty/binary/overlap مرفوضة؛ لا فحص عشوائي لكلRUNNER_TEMP أو_logs.

## CI وحدود العمليات

خمسةjobs حاجزة: API، Web، No committed secrets، Python dependency audit، npm dependency audit.
Actions مثبتة إلىfull SHA منالمصدر الرسمي؛ contents:read وpersist-credentials:false وtimeouts.
فرعcodex مشمول فيpush. لاpull_request_target أوproduction credentials أوتعديلbranch protection.

Full Ruff lint/Mypy محفوظتان. أضيف تنسيق أدواتCI واختباراتG5 وPrettier للواجهة وAlembic check.
لم يُفرضformatter جديد علىملفاتPhase2C/2D القديمة، ولم تتغيرUI/RBAC بسبب فروق تنسيق تاريخية.

الغلاف يرفضtest success بلاعداد موجب صحيح، وSKIP/XFAIL/XPASS، وتعددmigration heads.
Windows child يبدأsuspended ثميربط بـJob Object خاص قبلالتنفيذ؛ POSIX يستخدمprocess group.
Timeout ينهيالشجرة المملوكة وينتظر ضمنحدود، حتىعند انتهاءparent وبقاءgrandchild ممسكًا بالـpipes.
Browser cleanup ينتظرAPI دائمًا ولايقبل143 إلا بعدTERM أرسله بنفسه؛ لا||true.

## الأوامر القابلة للتكرار

منجذر المشروع علىLinux/CI:

```sh
python .github/ci/gitleaks-gate.py source --output-dir /tmp/sahl-source-scan
uv venv --python python /tmp/sahl-pip-audit
uv pip sync --python /tmp/sahl-pip-audit/bin/python --require-hashes .github/ci/pip-audit.lock.txt
python .github/ci/dependency-audit.py python --output-dir /tmp/sahl-python-audit --audit-python /tmp/sahl-pip-audit/bin/python --uv uv
python .github/ci/dependency-audit.py npm --output-dir /tmp/sahl-npm-audit --node node --npm npm
python .github/ci/gitleaks-gate.py artifacts --scan-path _logs/security-artifacts --output-dir /tmp/sahl-artifact-scan
```

علىWindows تستخدمScripts/python.exe ومسارات الأدوات الفعلية و`--npm <npm-cli.js>`.
نسخةnpm المطلوبة11.11.0؛ تثبيتCI يتحقق منchecksum. لا.env أوcredential مطلوبة لتدقيقdependencies.

## النتائج النهائية

| البوابة | النتيجة |
| --- | --- |
| Gitleaks source/history/merge diffs | PASS، صفرfindings،453 ملفًا متتبعًا |
| Gitleaks artifacts/logs | PASS،26 ملفًا نصيًا، وstdout/stderr وlog PostgreSQL المعزول |
| pip-audit | PASS:50 project +1 build +28 scanner inventory entries، صفرadvisories |
| npm audit | PASS:350 lock nodes، صفرadvisories |
| Backend full | 996 PASS، بلاSKIP/XFAIL/XPASS |
| Frontend full | 225 PASS /29 files |
| Playwright Chromium | 7/7 PASS:5187 → FastAPI8010 → PostgreSQL17 disposable على5434 |
| Ruff /Mypy | PASS للتطبيق والاختبارات وأدواتCI |
| ESLint /TypeScript /Prettier /production build | PASS |
| Alembic check /head | PASS:0016_security_audit_retention |
| Migration round-trip | head→base→head PASS؛ و0016→0015→0016 معحفظaudit history ضمنFull Backend |
| RLS /ownership /grants /catalog /cleanup | PASS، بمافيهاG4 retention regressions |
| CI contracts /syntax | PASS؛ خمسةjobs وأسماءwrappers وBash syntax |
| Project locks /metadata | unchanged |

أضيفت167 حالةاختبار فيG5:46 Gitleaks،45 dependency audit،42 output/process lifecycle،
14 CI contract،20 لتصنيفmaintenance. كلها ضمن996؛ لا تُجمع الأعداد المستهدفة مرةثانية.

harness المتصفح علىWindows استخدمSelectorEventLoop المتوافق معPsycopg؛ لا تعديلللتطبيق.
فُصلOrigin الخاص بالمتصفح عنبيئةBackend full. أُوقف وحُذفPostgreSQL disposable، وأُزيل
entrypoint المؤقت، بعدcleanup وفحصالسجل وعدمظهورcredential الصيانة. التقريران خارجcommits.
المنافذ الرسمية5173/8010 ثابتة، و5187 للـbrowser test فقط، ولا استخدام8000.

**G5 operationally verified محليًا**، بلاvulnerability أوblocker داخلنطاقها.
لاGitHub CI run جديد هنا؛ تنفيذActions وربطrequired checks بالـSHA والإغلاق النهائي ينتظران
اعتمادG6. الحالةالمحلية19 PASS /3 PARTIAL، ولاادعاء بإغلاقPhase2E أوإثباتproduction controls.

## المراجع

- [Gitleaks8.30.1](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1).
- [pip-audit2.10.1 PyLockSource](https://github.com/pypa/pip-audit/blob/v2.10.1/pip_audit/_dependency_source/pylock.py).
- [uv export](https://docs.astral.sh/uv/reference/cli/#uv-export).
- [npm audit11](https://docs.npmjs.com/cli/v11/commands/npm-audit/).
- [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use).
