# Phase 2A — أساس الجهات وعزل PostgreSQL RLS

**الحالة:** التنفيذ والتحقق المحلي والبعيد مكتملان؛ إغلاق Group 5 ومراجعة PR والدمج بيد المالك.
**الفرع:** `feature/phase-2a-tenant-foundation` من `develop` عند `c9895e6`.
**خط الأساس السابق:** الوسم `pre-phase-2-baseline` (‏`main = ee3d3e5`).

هذه وثيقة نطاق Phase 2A المعتمد ونتائج تحقق إغلاقه. لا تمثل اعتماد Group 5 أو إذن الدمج
نيابةً عن المالك. يسجل §15 الدليل على commit التنفيذ؛ وتوثّق أدلة HEAD النهائي ورقم PR
وفحوصه في طلب المراجعة والتقرير الختامي.

**آخر قبول رسمي:** اعتمد المالك Group 4 عند `bf6733265290a19953f1ea1d15913495172b0a13`:
222 اختبار خلفية · 213 اختبار واجهة في 28 ملفًا · `03-test.ps1`: ‏17 PASS وخروج 0 ·
`0004_runtime_privilege_boundary` · دورة مهاجرات ناجحة · شجرة نظيفة.

**دليل الإغلاق في Group 5:** نجح المحلي و[GitHub CI رقم 34116651930](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/actions/runs/34116651930)
على `59811ff0c9d743e4c7fbde65f3c1e550c674ccfb`: ‏222 Backend و213 Frontend،
وبوابات محلية 17 PASS. اجتازت المعايير التقنية الخمسة والثلاثون مراجعة §11؛ تبقى مراجعة
المالك وفحوص PR النهائية قبل الدمج.

---

## 1. النطاق

**داخل النطاق:** نموذج الجهة وهويتها ودورة حياتها · تجريد سياق الجهة · حدّ معاملة واعٍ بالجهة ·
سياسات PostgreSQL RLS مع `FORCE` · فصل دور المهاجر عن دور التطبيق · الفشل المغلق ·
اختبارات عزل مباشرة وسلبية · بوابات أمنية محلية وفي CI · استراتيجية المهاجرات · توثيق أمني.

**خارج النطاق قطعًا:** المصادقة · تسجيل الدخول · الجلسات · JWT · SSO · RBAC · خدمة التفويض ·
أدوار المستخدمين · الاستمرارية الحقيقية لإعدادات الواجهة · وحدات الأعمال · محرك الجداول ·
محرك التقارير · الإشعارات · استخدام Redis · أي شاشة أعمال.

## 2. النقطة المعمارية الحاكمة

لا مصادقة في هذه المرحلة. لذلك **لا مسار HTTP يستطيع إنشاء سياق جهة من بيانات العميل.**

الجواب ليس ثغرة مؤقتة ولا حالة خاصة، بل **تنفيذ يرفض دائمًا**:

| التنفيذ | المصدر | من يستعمله |
|---|---|---|
| `NoTenantResolver` | لا مصدر — يرفع دائمًا | **الافتراضي لكل HTTP، بلا استثناء** |
| `ExplicitTenantResolver` | قيمة تُمرَّر برمجيًا | طبقة الخدمة والاختبارات **فقط** |

وفي Phase 2B يُسجَّل تنفيذ ثالث يقرأ الهوية — **دون لمس سياسة RLS واحدة ولا حدّ معاملة واحد**.

## 3. القرارات المعتمدة

| # | القرار | المعتمد |
|---|---|---|
| D1 | نوع `tenant_id` | UUIDv7 من `uuid.uuid7()` في Python 3.14 حصرًا، بلا UUIDv4 fallback ولا مكتبة خارجية — ADR-0014 |
| D2 | `status` داخل سياسة RLS | **لا** — العزل عن الهوية وحدها، والحالة قرار تفويض في الخدمة |
| D3 | إنشاء الجهات بلا مصادقة | بدور المهاجر في fixtures فقط · `sahl_app` بلا SELECT أو منح كتابة على `tenants` |
| **D4** | **جدول الفحص المملوك** | **معدَّل — انظر §4** |
| D5 | رمز HTTP للسياق المفقود | `500 internal_error` + حدث سجل `tenant_context_missing` |
| D6 | نقطة نهاية توضيحية | **لا** — `require_tenant_context()` مكتوبة ومُختبَرة بدلًا منها |
| D7 | `sahl_migrator` محليًا | **إلزامي** |
| D8 | `get_session()` | **حُذفت** — خدمات الجهات تمر عبر حد المعاملة في ADR-0015 |
| D9 | `slug` | الآن، لا في 2B |
| D10 | جدول تدقيق | لا — توثيق فقط؛ الجدول في 2D |
| D11 | `public.tenants` | جدول منصّة، بلا `tenant_id` وبلا tenant RLS أو سياسة على `id` — قرار Group 4 وADR-0016 |

### 4. D4 المعدَّل — جدول الفحص ليس جزءًا من المخطط

**`tenant_scoped_probe` ليس مهاجرة ولا جدولًا دائمًا في مخطط الإنتاج.**

هو **fixture حقيقية في PostgreSQL** بدورة حياة كاملة داخل الاختبار:

1. `sahl_migrator` ينشئ الجدول
2. يطبّق عليه `ENABLE ROW LEVEL SECURITY` و`FORCE ROW LEVEL SECURITY` والسياسة والمنح — **نفس العقد حرفيًا** الذي يطبَّق على أي جدول مملوك
3. الاختبارات تعمل عليه بدور **`sahl_app`** حصرًا
4. `DROP` في التفكيك

**لماذا هذا أصح:** مخطط الإنتاج لا يحمل جدولًا لا معنى له، ولا دين تقني يجب تذكّر حذفه لاحقًا،
ومع ذلك يبقى برهان العزل على **جدول مملوك حقيقي** خاضع للعقد نفسه. تبقى مهاجرات Phase 2A
**ثلاثًا** (`0002` إلى `0004`)؛ الأخيرة تسحب المنح القديمة، ولا واحدة منها تخص الفحص.
الجدول فعلي عابر لعمر الاختبار، لا SQL TEMP TABLE مقصور على اتصال واحد. بعد teardown
يجب ألا يبقى جدول أو سياسة أو نوع أو دالة أو تسلسل اختباري.

## 5. القيود الإضافية الملزمة

1. **أول عمل في المرحلة** هو الفصل الحقيقي: `MIGRATION_DATABASE_URL → sahl_migrator/Alembic`
   و`DATABASE_URL → sahl_app/runtime`.
2. `migrations/env.py` **يُمنع** أن يستعمل عنوان التشغيل باعتباره عنوان المهاجرات.
3. **بوابة تفشل** إن عملت المهاجرات بدور التطبيق في development أو test أو CI.
4. الجداول التي تنشئها المهاجرات **يجب ألا تكون مملوكة لـ`sahl_app`**.
5. سياق الجهة داخل PostgreSQL **حصرًا** عبر
   `SELECT set_config('app.tenant_id', <bound parameter>, true)`.
6. **ممنوع:** `SET` على مستوى الجلسة · `set_config(..., false)` · تركيب SQL نصيًا.
7. `app.current_tenant_id()`: ‏`STABLE` · **ليست** `SECURITY DEFINER` · الغائب أو الفارغ → `NULL` ·
   الـUUID الصالح → `uuid` · **بلا أي fallback ولا جهة منصّة**.
8. HTTP: ‏`NoTenantResolver` هو الافتراضي دائمًا. **لا `X-Tenant-ID`**، ولا body ولا query ولا header
   ينشئ سياقًا.
9. `ExplicitTenantResolver` للخدمة والاختبارات فقط، **ويُمنع تسريبه إلى تركيب الـAPI** — بحارس ثابت.
10. اختبار `pool_size=1` وإعادة استخدام الاتصال **شرط قبول ملزم**.
11. الفحص ليس واحدًا من المهاجرات الثلاث.

## 6. فصل الأدوار وإغلاق أعطال المجموعة الثانية

**السياق التاريخي:** كانت المهاجرات المحلية تستعمل عنوان دور التطبيق، بينما كان CI يمرر
عنوان المهاجر بصورة مختلفة. أُغلق هذا المسار بفصل `MIGRATION_DATABASE_URL` عن
`DATABASE_URL` ومنع دور التطبيق في Alembic، بلا fallback.

**المجموعة الثانية مقبولة رسميًا:** أُصلح حق إنشاء المخطط بمنح `CREATE ON DATABASE`
للمهاجر على قاعدة المشروع فقط، مع بقاء `CREATEDB` و`CREATEROLE` و`SUPERUSER` و`BYPASSRLS`
معطلة وبقاء التطبيق بلا `CREATE`. وصار فحص دور Alembic داخل ترتيب معاملة مقصود لا يترك
معاملة ضمنية تتراجع عند إغلاق الاتصال. بوابة المهاجرات تفشل برمز خروج غير صفري عند الخطأ،
وتثبت الوصول الفعلي إلى head قبل اختبارات قاعدة البيانات. قُبلت المجموعة الثانية عند
`b0617e4fd95c2ff3953207eb1ee3d75c2309255c`؛ تحافظ نتائج الإغلاق في §15 على هذه العقود.

## 7. تصميم العزل المعتمد للمجموعة الرابعة

دالة واحدة في مخطط `app` مملوك للمهاجر:

```
app.current_tenant_id() RETURNS uuid
    STABLE · NOT SECURITY DEFINER
    غائب أو فارغ أو غير صالح → NULL
```

التعبير الخام `current_setting('app.tenant_id', true)::uuid` **يرمي خطأً** على النص الفارغ؛
الدالة تحوّله إلى `NULL`، و`NULL` لا يطابق شيئًا → صفر صفوف. الفشل المغلق يصير **قاعدة صريحة**.

السياسة الموحّدة لكل جدول مملوك:

```
ENABLE ROW LEVEL SECURITY
FORCE  ROW LEVEL SECURITY
POLICY tenant_isolation FOR ALL TO sahl_app
    USING      (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id())
```

`USING` يحكم القراءة والتحديث والحذف · `WITH CHECK` يمنع **زرع** صف في جهة أخرى و**نقل** صف إليها.

`public.tenants` جدول منصّة لا جدول مملوك (FR-MT-07). **حسم المالك إلغاء اقتراح السياسة
الخاصة السابقة**: بلا `tenant_id`، وبلا tenant RLS أو استعمال `current_tenant_id()` لعزل صفوفه،
وبلا SELECT أو WRITE للتطبيق. لا Platform Tenant. حاجة مستقبلية إلى القراءة تعالج بمنح
وتفويض في مرحلتها، لا بصلاحيات استباقية هنا. القرار في ADR-0016.

`ENABLE` وحدها لا تكفي: المالك يتجاوز السياسات افتراضيًا. `FORCE` يُخضع وصول المالك إلى
الصفوف للسياسة، لكنه لا يسلب منه DDL ولا يلغي `SUPERUSER/BYPASSRLS`. لذلك يبقى runtime
غير مالك وبلا تلك الصفات أو عضويات التصعيد وفق ADR-0017. تطبّق سياسة المجموعة الرابعة
على probe داخل fixture فقط؛ لا سياسة إنتاج على `tenants`.

## 8. الفشل المغلق في ثلاث طبقات

| الطبقة | الآلية | النتيجة |
|---|---|---|
| قاعدة البيانات بعد تطبيق السياسات | `app.current_tenant_id()` = NULL داخل المقارنة | صفر صفوف للقراءة · رفض للإدراج |
| حدّ المعاملة | لا يُفتح بلا `TenantContext` وهوية صالحة | رفض قبل فتح الجلسة أو أي SQL |
| HTTP | `NoTenantResolver` افتراضيًا | رفض قبل بلوغ أي خدمة |

نُفّذ رفض HTTP وحدّ المعاملة في المجموعة الثالثة. تثبت الرابعة منع الوصول إلى صفوف probe
بالسياسة الفعلية؛ إعادة `NULL` من الدالة وحدها ليست سياسة عزل.

## 9. المهاجرات — ثلاث، عكوسة كل واحدة وحدها

| المهاجرة | الأثر |
|---|---|
| `0002_tenant_foundation` | مخطط `app` · نوع الحالة · جدول `tenants` · الفهارس والقيود |
| `0003_tenant_context_function` | `app.current_tenant_id()` والمنح |
| `0004_runtime_privilege_boundary` | سحب منح `tenants` القديمة وإزالة default grants الواسعة؛ بلا جدول أو سياسة إنتاج |

استُبدل الاسم المخطط `0004_tenant_isolation_policies` بعد قرار إبقاء `tenants` خارج tenant RLS.
لا probe في سلسلة المهاجرات. `downgrade` للرابعة يعيد عقد منح 0003 المعروف، ثم يعيد upgrade
حدود المنح المقصودة. دورة `downgrade base → upgrade head` بوابة قائمة في CI، ويجب التحقق
من وصول القاعدة الفعلي إلى head؛ التفصيل في ADR-0017 و`migrations/README.md`.

## 10. سيناريوهات الهجوم — A1..A13

يعتمد الجدول **ترقيم اعتماد المجموعة الرابعة الأخير**، بدور `sahl_app` مع Tenant A وTenant B.
الفحص على probe حقيقية، وSQL/ORM دون الاعتماد على مرشح جهة يضيفه التطبيق.

| # | السيناريو | المتوقَّع |
|---|---|---|
| A1 | A يقرأ صفوف A | صفوف A تظهر |
| A2 | A يقرأ صفوف B، بما فيها معرّف كامل | صفر صفوف |
| A3 | B يقرأ صفوف A | صفر صفوف |
| A4 | A يحدّث صف B | صفر صفوف متأثرة |
| A5 | A يحذف صف B | صفر صفوف متأثرة |
| A6 | A يُدرج بـ`tenant_id = B` | رفض PostgreSQL بـWITH CHECK وعدم إضافة الصف |
| A7 | A يغيّر `tenant_id` لصفه إلى B | رفض PostgreSQL بـWITH CHECK وبقاء جهة الصف الأصلية |
| A8 | بلا سياق: SELECT | صفر صفوف |
| A9 | بلا سياق: UPDATE وDELETE | صفر صفوف متأثرة |
| A10 | سياق غير صالح | لا وصول؛ الدالة NULL والسياسة تفشل مغلقًا |
| A11 | SQL مباشر تحت السياق المحدد | لا يتجاوز RLS |
| A12 | SQLAlchemy/ORM تحت السياق المحدد | لا يتجاوز RLS |
| A13 | انتهاء المعاملة ثم إعادة استعمال الاتصال | السياق لا يبقى |

A13 يتضمن Engine حقيقيًا بـ`pool_size=1` وإثبات هوية الاتصال/backend PID نفسه: بعد commit،
ثم rollback، ثم exception تكون الدالة NULL وSELECT بلا سياق صفر صفوف؛ ثم A إلى B بلا تسرب.
غياب السياق لا يجيز INSERT أيضًا؛ يختبر رفض WITH CHECK صراحة.

### مطابقة الترقيم السابق

| السابق | المقابل في اعتماد المجموعة الرابعة |
|---|---|
| A1: قراءة A لصف B | A2 |
| A2: تحديث صف B | A4 |
| A3: حذف صف B | A5 |
| A4: إدراج صف لـB | A6 |
| A5: نقل صف A إلى B | A7 |
| A6: قراءة بلا سياق | A8 |
| A7: إدراج بلا سياق | إثبات إضافي لـWITH CHECK بجانب A8/A9 |
| A8: سياق فارغ أو غير صالح | A10 واختبارات الفشل المغلق |
| A9: UUID غير موجود | حالة إضافية لا تطابق صفًا؛ ليست A9 في الترقيم الجديد |
| A10: تصفير السياق بعد المعاملة | A13 |
| A11: SELECT على `tenants` يعيد صف الجهة | **ملغى بقرار المالك**؛ يحل محله حارس عدم منح التطبيق SELECT على جدول المنصّة |
| A12: رفض كتابة `tenants` | حارس منح جدول المنصّة مستقل؛ A12 الجديد لاختبارات ORM |
| A13: معاملة متداخلة تغيّر السياق | ليس توسعة مطلوبة الآن؛ A13 المعتمد لانتهاء المعاملة وإعادة استعمال الاتصال |

أضيفت صراحةً القراءة الإيجابية A1، والاتجاه المقابل A3، ومنع التعديل بلا سياق A9،
وتمييز SQL المباشر A11 عن ORM A12. لا يعاد استعمال أرقام الخطة القديمة في تقرير النتائج.

## 11. مراجعة شروط الخروج — `PHASE-2A-GATE`

ترقيم المعايير مطابق لاعتماد Group 5. الحالة **PASS** أدناه نتيجة فنية مثبتة على
`59811ff0c9d743e4c7fbde65f3c1e550c674ccfb` باختبارات المحلي وCI في §15 أو بالمراجعة
المباشرة المبينة في الدليل. RLS مُثبت على fixture حقيقية، ولا توجد جداول أعمال مملوكة
لجهة في مخطط الإنتاج عند الإغلاق.

| # | المعيار | الحالة | الدليل |
|---|---|---|---|
| 1 | Tenant model موجود | PASS | [النموذج](../apps/api/app/models/tenant.py) و[test_tenant_foundation](../apps/api/tests/db/test_tenant_foundation.py) |
| 2 | Tenant ID = UUIDv7 | PASS | `new_tenant_id()` واختبارات الإصدار والتفرّد والترتيب في [test_tenant_model](../apps/api/tests/test_tenant_model.py) |
| 3 | عقد slug مطبق | PASS | تحقق المجال وUNIQUE/CHECK بالمهاجرة؛ [حارس تطابق القيد](../apps/api/tests/test_migration_slug_contract.py) |
| 4 | lifecycle الجهة مطبق | PASS | enum ورسم الانتقالات ودوال المجال في [النموذج واختباراته](../apps/api/tests/test_tenant_model.py)؛ ليس API إدارة أو تفويضًا |
| 5 | فصل migrator عن runtime | PASS | [إعدادات العنوانين](../apps/api/tests/test_config.py) و[migration transaction](../apps/api/tests/test_migration_transaction.py) ودورة CI |
| 6 | `sahl_app` ليس owner | PASS | [حارس الملكية](../apps/api/tests/db/test_rls_catalog.py): صفر relations/schemas/functions/types/databases |
| 7 | ليس SUPERUSER | PASS | [حارس الأعلام والعضويات](../apps/api/tests/db/test_rls_catalog.py): `rolsuper=false` |
| 8 | ليس BYPASSRLS | PASS | الحارس نفسه: `rolbypassrls=false` |
| 9 | ليس CREATEDB | PASS | الحارس نفسه: `rolcreatedb=false` |
| 10 | ليس CREATEROLE | PASS | الحارس نفسه: `rolcreaterole=false` وعضويات runtime صفر |
| 11 | TenantContext صريح | PASS | [test_tenant_context](../apps/api/tests/test_tenant_context.py): هوية مطلوبة جامدة ومتحقق منها |
| 12 | HTTP default = NoTenantResolver | PASS | [HTTP dependency](../apps/api/app/api/dependencies.py) و[test_tenant_http_context](../apps/api/tests/test_tenant_http_context.py) |
| 13 | ExplicitTenantResolver خارج production API wiring | PASS | [حارس الاستيراد بما فيه re-exports](../apps/api/tests/test_tenant_resolver_boundary.py) واختبار factory |
| 14 | السياق transaction-local فقط | PASS | [حد المعاملة](../apps/api/app/db/tenant_transaction.py) و[اختبارات الاتصال الحقيقي](../apps/api/tests/db/test_tenant_transaction.py) |
| 15 | `set_config(..., true)` فقط | PASS | [حارس النص والمعامل المربوط ومنع session-level SET](../apps/api/tests/test_tenant_transaction_contract.py) |
| 16 | `current_tenant_id()` تفشل مغلقًا | PASS | [اختبارات الدالة](../apps/api/tests/db/test_current_tenant_id.py): الغائب والفارغ وغير الصالح NULL، STABLE وINVOKER |
| 17 | RLS = ENABLE + FORCE | PASS | [catalog guard](../apps/api/tests/db/rls_catalog.py) و[رفض إضعاف العقد](../apps/api/tests/db/test_rls_catalog.py) |
| 18 | USING + WITH CHECK | PASS | الحارس نفسه يطابق التعبيرين؛ [رفض كتابة الجهة الأخرى](../apps/api/tests/db/test_rls_attack_matrix.py) |
| 19 | SQL المباشر لا يتجاوز العزل تحت السياق المحدد | PASS | A11 في [مصفوفة الهجوم](../apps/api/tests/db/test_rls_attack_matrix.py)، دون WHERE للجهة |
| 20 | ORM لا يتجاوز العزل تحت السياق المحدد | PASS | A12 في المصفوفة: قراءة وCRUD ورفض WITH CHECK بلا tenant filters |
| 21 | Cross-tenant SELECT ممنوع | PASS | A2/A3: المعرّف الكامل للصف الأجنبي يعيد صفر صفوف، في الاتجاهين |
| 22 | Cross-tenant UPDATE ممنوع | PASS | A4 وORM: صفر صفوف متأثرة |
| 23 | Cross-tenant DELETE ممنوع | PASS | A5 وORM: صفر صفوف متأثرة |
| 24 | Cross-tenant INSERT ممنوع | PASS | A6 وORM: رفض PostgreSQL بـSQLSTATE `42501` وثبوت عدم الكتابة |
| 25 | نقل tenant_id ممنوع | PASS | A7 وORM: رفض `42501` وبقاء هوية الصف الأصلية |
| 26 | Missing context = zero access | PASS | A8/A9 وORM: SELECT صفر، UPDATE/DELETE صفر، INSERT مرفوض؛ الخدمة ترفض قبل الجلسة |
| 27 | Invalid context = zero access | PASS | A10 وORM: الفارغ وغير الصالح بلا وصول؛ اختبار UUID غير مطابق كذلك |
| 28 | pool_size=1 leak test | PASS | [أربع حالات pool](../apps/api/tests/db/test_rls_pool_reuse.py): PID نفسه بعد commit/rollback/exception ثم A إلى B |
| 29 | حارس tenant-owned tables موجود | PASS | [اكتشاف catalog عبر tenant_id](../apps/api/tests/db/rls_catalog.py)، بلا قائمة أسماء ثابتة؛ حراس سلبية |
| 30 | probe fixture مؤقتة بلا أثر | PASS | [lifecycle نجاح/استثناء](../apps/api/tests/db/test_rls_fixture_lifecycle.py) و[post-test guard](../apps/api/tests/db/verify_clean_database.py) |
| 31 | tenants جدول منصّة بلا tenant RLS | PASS | [حارس الجدول والمنح](../apps/api/tests/db/test_rls_catalog.py): لا tenant_id ولا سياسة ولا SELECT/WRITE للتطبيق |
| 32 | Local Gates | PASS | [سجل 03-test على 59811ff](../_logs/03-test-20260907-142620.log): ‏17 PASS وخروج 0 وشجرة نظيفة قبل/بعد |
| 33 | GitHub CI | PASS | [run 34116651930 على 59811ff](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/actions/runs/34116651930): الوظائف الثلاث ناجحة |
| 34 | BRD/SRS لم تتغيرا | PASS | مقارنة الملفين byte-for-byte مع `develop`: متطابقان؛ لا يظهران في فرق Phase 2A |
| 35 | لا كود Phase 2B | PASS | مراجعة [فرق التنفيذ](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/compare/c9895e6...59811ff): لا Auth/User/Memberships/JWT/RBAC أو وظائف 2B |

بقية شروط الخطة محفوظة: دورة المهاجرات العكوسة والوصول إلى head، ورفض SKIP/XFAIL/XPASS،
وغياب continue-on-error، والمنح المحددة ورفض DDL، ومراجعة ADR-0014 إلى ADR-0017.
قُبلت مجموعتا السياق والعزل صراحةً من المالك في نقطتيهما المسجلتين.

**حد الدليل:** يخص هذا الجدول commit التنفيذ 59811ff. توثّق أدلة HEAD النهائي ورقم PR
وفحوصه في طلب المراجعة والتقرير الختامي، مع الحفاظ على شرط الخطة الأصلي «CI أخضر على PR
بالوظائف الثلاث». قبول Group 5 النهائي وإذن الدمج يظلان بيد المالك.

## 12. الأعمال المؤجلة والدين التقني المعروف

هذه البنود ليست إخفاقات في معيار عزل Phase 2A، ولا يجيز تسجيلها تنفيذ مرحلة لاحقة.

| البند | الوضع عند الإغلاق | الاستحقاق أو حد النطاق |
|---|---|---|
| إنشاء الجهات وإدارتها وقراءة جدول المنصّة من التطبيق | لا مسار HTTP ولا منح runtime استباقية؛ fixtures إدارية فقط | تصميم مصادقة وتفويض معتمد في المرحلة المناسبة بعد 2A |
| مصدر TenantContext مصادَق عليه | HTTP يرفض دائمًا؛ ExplicitResolver للخدمة والاختبار | 2B بعد اعتماد نطاقها؛ لا تغيير لـRLS لتجاوز ذلك |
| `slug` بلا مستهلك | عقده مكتمل لكنه ليس مصدر ثقة | مسارات الجهة المعتمدة لاحقًا |
| تفويض حالات الجهة | enum ورسم الانتقالات مطبّقان؛ رفض أعمال الجهة الموقوفة يحتاج خدمة وتفويضًا غير موجودين في 2A | 2B مع RBAC أو مرحلتهما المعتمدة؛ الحالة لا تدخل RLS |
| التدقيق | لا جدول audit ضمن 2A | 2D حسب خطة المرحلة |
| سياسة أول جدول أعمال مملوك لجهة | لا جدول إنتاج مملوك الآن؛ البرهان على probe، والحارس جاهز | المهاجرة التي تضيف الجدول: tenant_id UUID NOT NULL مفهرس وفق SRS، والملكية وRLS والمنح واختبارات العزل |
| سياق الواجهة وإعداداتها التجريبية | `preview-tenant` وbrowser storage وpreview permissions أدوات معاينة، بلا هوية موثوقة أو حماية | الربط الحقيقي والتخزين والتفويض في نطاق لاحق معتمد؛ ADR-0010 |
| عينات Table/Print | عرض ساكن بعقود موجودة؛ ليست محركات أعمال | تزال عندما تأتي المحركات المعتمدة؛ ADR-0012 |
| Redis الحقيقي | مؤجل تشغيليًا، دون بديل داخل منطق المنتج | قبل إغلاق Phase 3 وفق ADR-0003 |
| تحديث التبعيات آليًا | قفل uv والبوابات موجودان؛ لا إعداد Dependabot/Renovate مودع حاليًا | متابعة مستقلة لسياسة ADR-0013؛ لا ترقيات أو أداة جديدة في Group 5 |

**أُغلق داخل Phase 2A:** فصل عناوين المهاجر/runtime، وحق CREATE للمهاجر على قاعدة المشروع
دون CREATEDB، وترتيب معاملة Alembic، وفشل بوابة المهاجرات وإثبات head، واستبدال توصية
SET LOCAL بـ`set_config(..., true)` مربوط، وإزالة default grants الواسعة، وبرهان RLS
والـpool والتنظيف. لا دين ناتج من probe دائمة؛ لا أثر لها بعد الاختبارات.

## 13. المجموعة الثالثة — التنفيذ والتحقق

**مقبولة رسميًا من المالك عند `e91c30f98ea309b3326c2ee48c7fca9ee8620bb4`.**
الخلفية 153 passed؛ الواجهة 213 passed في 28 ملفًا؛ `03-test.ps1` بنتيجة 16 PASS وخروج 0؛
قاعدة PostgreSQL الفعلية عند `0003_tenant_context_function`، وشجرة العمل نظيفة عند القبول.

تشمل الخلفية 88 اختبارًا سابقًا و65 جديدًا: 36 للسياق وHTTP، و7 اختبارات وحدة لحد المعاملة،
و14 للدالة، و8 لحد المعاملة على PostgreSQL. هذه نقطة انطلاق الرابعة، لا نتيجة تحققها.

- `TenantContext` جامد بهوية `TenantId` مطلوبة ومتحقق منها عند حد التحويل الموثوق.
- `NoTenantResolver` افتراضي HTTP، و`ExplicitTenantResolver` للخدمة والاختبار مع حارس للحدود.
- `tenant_transaction(context)` يرفض السياق المفقود أو غير الصالح قبل الجلسة، ثم يفتح
  معاملة صريحة ويضبط `set_config` بمعامل مربوط و`true` ويدير commit/rollback وإغلاق الجلسة.
- مهاجرة `0003_tenant_context_function` مستقلة وعكوسة للدالة `STABLE` و`SECURITY INVOKER`.
  الغائب والفارغ وغير الصالح تعيد `NULL`؛ UUID الصالح يعاد كما هو، بلا بحث أو جهة افتراضية.
- اختبارات وحدة وخدمة وPostgreSQL حقيقية لعمر السياق والرفض والتراجع، وحراس منع الانحراف.
- القرار التفصيلي في [ADR-0015](adr/ADR-0015-tenant-context-and-transactions.md).

**لا يدخل هنا:** سياسات RLS · `tenant_scoped_probe` · مصفوفة الهجمات · اختبار التسرب النهائي
`pool_size=1` · الحسم من بيانات HTTP · المصادقة والجلسات وJWT وRBAC. يبقى `tenants` جدول منصّة.

## 14. المجموعة الرابعة — التنفيذ والقبول

**مقبولة رسميًا من المالك عند `bf6733265290a19953f1ea1d15913495172b0a13`.**
الخلفية 222 passed، والواجهة 213 passed في 28 ملفًا، و`03-test.ps1` ‏17 PASS وخروج 0،
ودورة المهاجرات ناجحة عند `0004_runtime_privilege_boundary`، وشجرة نظيفة.
اختبارات الخلفية على PostgreSQL 17 الحقيقي مع `--strict-security-gates`:
153 اختبارًا سابقًا و69 جديدًا:

| اختبارات المجموعة الرابعة الجديدة | العدد |
|---|---:|
| مصفوفة SQL/ORM | 25 |
| حراس الكتالوج على القاعدة | 15 |
| إعادة استعمال اتصال pool | 4 |
| رفض DDL بدور runtime | 7 |
| دورة حياة fixture | 2 |
| وحدة: تطبيع تعبير السياسة | 7 |
| وحدة: نمط البوابة الصارم | 5 |
| وحدة: عقود بوابات الجودة | 4 |
| **المجموع** | **69** |

منها **53 اختبار PostgreSQL فعليًا و16 اختبار وحدة**. نجح `verify_clean_database`
بعد pytest: لا آثار probe، وصفر جداول إنتاج مملوكة لجهة؛ `tenants` جدول منصّة.
نجحت أيضًا **25 حالة** لاختبار تنسيق تشغيل بوابات PowerShell، مستقلة عن عدد Backend.
أُعيد التحقق المحلي والبعيد ضمن Group 5 على commit الإصلاح المبين في §15.

بدأ نطاقها باعتماد المالك Group 3 وقراره الملزم لـ`tenants`. شمل:

1. probe ضمن fixture فقط، بملكية المهاجر و`tenant_id UUID NOT NULL` وسياسة ENABLE/FORCE
   وUSING/WITH CHECK، ومنح CRUD الضرورية للتطبيق وDROP مضمون في teardown.
2. مصفوفة §10 بالـSQL المباشر وORM، وإثبات رفض INSERT ونقل tenant_id، والفشل المغلق،
   واختبار التسرب على اتصال حقيقي مع `pool_size=1`.
3. اكتشاف الجداول المملوكة عبر عمود `tenant_id` والكتالوج، وحراس RLS والسياسة والملكية
   وأعلام الأدوار والمنح دون الاعتماد على أسماء ثابتة وحدها.
4. إزالة المنح القديمة من `tenants` وdefault grants الواسعة في التهيئة المحلية وCI،
   ومهاجرة `0004_runtime_privilege_boundary` العكوسة؛ بلا policy أو جدول إنتاج جديد.
5. [ADR-0016](adr/ADR-0016-tenant-rls-enforcement.md) و[ADR-0017](adr/ADR-0017-database-role-separation.md)،
   واختبارات blocking ضمن `03-test.ps1` وCI القائم على PostgreSQL 17.

يفشل `--strict-security-gates` عند نتائج pytest الفعلية SKIP أو XFAIL أو XPASS.
يعمل `python -m tests.db.verify_clean_database` بعد pytest محليًا حتى عند فشله،
وفي CI بخطوة `if: always()`؛ بقاء أثر اختباري أو إخلال عقد RLS المكتشف يفشل البوابة.

نتيجة A1–A13 وWITH CHECK وSQL/ORM وإعادة استعمال الاتصال والحراس PASS ضمن التشغيل
الكامل. يثبت §15 بوابة الإغلاق المحلية وCI على commit التنفيذ نفسه مع السجلات الدقيقة.

لا Authentication أو Sessions أو JWT أو RBAC أو Authorization Service أو Platform Admin
bypass أو Business Modules أو Redis أو Docker أو OCI أو Terraform أو DataTable أو Reports.
خدمة PostgreSQL 17 القائمة في CI تبقى، ولا ملفات Docker جديدة. لا تعديل BRD أو SRS.

بعد قبول الرابعة أجاز المالك Group 5 للإغلاق والتحقق البعيد فقط. لا يبدأ Phase 2B،
ولا يتم الدمج، ضمن هذا التفويض.

## 15. المجموعة الخامسة — دليل الإغلاق والتحقق البعيد

**commit التنفيذ المختبَر:** `59811ff0c9d743e4c7fbde65f3c1e550c674ccfb`.
**الفرع المنشور:** `feature/phase-2a-tenant-foundation`، والـPR المستهدف إلى `develop`.
لم تُضف هذه المجموعة وظائف أو مهاجرات جديدة.

### إصلاح توافق CI المحدود

فشل [التشغيل الأول 34116302271](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/actions/runs/34116302271)
على `bf6733265290a19953f1ea1d15913495172b0a13` في اختبارَي config يفترضان غياب
`MIGRATION_DATABASE_URL`، بينما CI يعرّفه عمدًا. نجحت الاختبارات الـ220 الأخرى والحراس.

أُعيد إنتاج السبب، ثم عُزل متغير البيئة داخل الاختبارين بـ`monkeypatch.delenv` في
`test_config.py` فقط. commit ذري `59811ff` بتغيير `+6/-2`؛ نجحت اختبارات config
الثمانية قبل إعادة البوابات كاملة. لم يُخفّف حارس ولم يتغير runtime أو Stack أو نطاق RLS.

### نتائج المحلي وGitHub

| الدليل على 59811ff | النتيجة |
|---|---|
| `scripts/03-test.ps1` | **17 PASS / exit 0**؛ شجرة نظيفة قبل التشغيل وبعده |
| Backend محليًا | **222 passed** في 15.53 ثانية مع `--strict-security-gates` |
| Frontend محليًا | **213 passed / 28 files** |
| PostgreSQL | **17.11**؛ head النهائي **`0004_runtime_privilege_boundary`** |
| المهاجرات محليًا | **0004 → base → 0004 PASS**؛ قُرئت base الخالية فعليًا بعد downgrade ثم head النهائي |
| المهاجرات في CI | **0004 → base → 0004 PASS**؛ السجل يثبت انتقالات downgrade/upgrade وتُقرأ حالة head النهائية |
| حارس ما بعد الاختبارات | **PASS**؛ لا آثار probe و**0 production tenant tables** |
| GitHub Actions | **[34116651930: success](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/actions/runs/34116651930)** على SHA التنفيذ أعلاه |
| [API — job 101724931615](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/actions/runs/34116651930/job/101724931615) | **success**؛ PostgreSQL 17، القفل والجودة، دورة المهاجرات والأدوار، 222 اختبارًا والنمط الصارم وحارس التنظيف |
| [Web — job 101724931578](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/actions/runs/34116651930/job/101724931578) | **success**؛ lint وtypes و213 اختبارًا في 28 ملفًا وbuild |
| [No committed secrets — job 101724931626](https://github.com/visionit30-a11y/Vision_Sahl_Advanced_v.01/actions/runs/34116651930/job/101724931626) | **success** |

الأدلة المحلية المحفوظة: [سجل البوابات](../_logs/03-test-20260907-142620.log)،
[بيانات CI](../_logs/group5-ci-34116651930.json)،
[سجلات وظائف CI](../_logs/group5-ci-34116651930-logs.zip).
هذه ملفات تحقق محلية في `_logs` وليست ملفات يُطلب إيداعها في Git؛ رابط Actions هو الدليل البعيد.

الحالة النهائية للمخطط مقصودة: `public.tenants` جدول منصّة بلا tenant_id أو tenant RLS
أو منح runtime؛ `app.current_tenant_id()` موجودة. غياب سياسة إنتاج لا ينفي البرهان:
السياسة تُنشأ على fixture حقيقية ويثبت أثرها ثم تزال مع الجدول، والحارس يكتشف أي جدول
مملوك يُضاف لاحقًا. اختبارات الأدوار والمنح والملكية ورفض DDL ناجحة.

### المراجعة والتاريخ وحدود التسليم

رُوجعت `phase-2a.md` وجميع ADR-0001 إلى ADR-0017 ضمن Group 5. بقيت ADR-0001 إلى
ADR-0013 دون تعديل في الإغلاق. وضحت ADR-0014 إلى ADR-0017 الحالة المحسومة وروابط الإثبات.
BRD وSRS متطابقان byte-for-byte مع `develop`، ولم يتغير أي منهما.

نقاط التاريخ المرجعية: أساس الفرع `c9895e6`؛ قبول Group 2 عند `b0617e4`؛
قبول Group 3 عند `e91c30f`؛ commits Group 4 هي `e4a6f1a` للمنح، و`52ce7bf`
لبرهان RLS والـpool، و`4fe6b51` للبوابات، و`bf67332` للتوثيق المقبول؛
إصلاح Group 5 الوحيد في الكود هو `59811ff`. لا rebase أو squash أو إعادة كتابة تاريخ.

توثّق أدلة HEAD النهائي وcommit التوثيق ورقم PR إلى `develop` وروابط فحوصه في طلب
المراجعة والتقرير الختامي؛ دليل التنفيذ الثابت هنا هو 59811ff. **قبول Group 5 والدمج
بيد المالك**: لا Merge آلي ولا بدء Phase 2B.
