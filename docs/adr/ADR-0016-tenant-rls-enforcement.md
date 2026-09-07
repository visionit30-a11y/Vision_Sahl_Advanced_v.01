# ADR-0016: إنفاذ عزل الجهات بواسطة PostgreSQL RLS

- **الحالة:** منفّذ في المجموعة الرابعة؛ Backend ‏222 passed مع البوابة الصارمة وحارس القاعدة بعد الاختبارات ناجحان؛ القبول النهائي بيد المالك.
- **التاريخ:** 2026-09-07
- **المرحلة:** Phase 2A — المجموعة المنطقية الرابعة
- **المرجع:** SRS §6، وADR-0014، وADR-0015، واعتماد المالك المجموعة الثالثة عند `e91c30f` ونطاق الرابعة.
- **يحل محل:** اقتراح سياسة على `public.tenants` ومصفوفة A1–A13 القديمة في خطة Phase 2A؛ جدول المطابقة في §10 من الخطة.

## السياق والقرار

سياق الجهة وحدّ معاملتها موجودان وفق ADR-0015. إضافة شرط في استعلام الخدمة وحدها
يمكن نسيانها في مسار جديد. يعتمد المشروع PostgreSQL RLS لإنفاذ عزل الصفوف عند تنفيذ
SQL وSQLAlchemy/ORM بدور التشغيل نفسه، حتى دون مرشح جهة في الاستعلام.

تعمل RLS مع منح SQL ولا تستبدلها. `ENABLE` يفعّل تطبيق السياسات، و`FORCE` يُخضع المالك
أيضًا لها عند الوصول إلى الصفوف. لا تمنع `FORCE` صلاحيات تعديل السياسة لدى المالك،
ولا تتغلب على `SUPERUSER` أو `BYPASSRLS`؛ لذلك فصل المالك عن runtime إلزامي.
[مرجع PostgreSQL 17 لسياسات الصفوف](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).

### 1. جدول المنصّة خارج tenant RLS

قرار المالك: `public.tenants` جدول منصّة، بلا `tenant_id` وبلا tenant RLS أو سياسة
تستخدم `app.current_tenant_id()` على `id`. لا توجد جهة منصّة افتراضية.
لا حاجة تشغيلية مثبتة لقراءة التطبيق هذا الجدول الآن، لذلك لا `SELECT` أو منح كتابة
لـ`sahl_app`. تعالج حاجة مستقبلية إلى القراءة بمنح وتفويض معتمدين في مرحلتهما.

هذا استثناء دلالي موثّق لجدول منصّة، وليس استثناءً يسمح بصفوف جهة دون عزل.
لا ينشئ هذا القرار Platform Admin أو خدمة تفويض. مسؤول المنصّة المستقبلي لا يعطل RLS
ولا يتلقى `BYPASSRLS` أو عضوية دور المهاجر؛ أي مسار إداري يحتاج تصميمًا واعتمادًا مستقلين.

### 2. برهان على fixture حقيقية ومؤقتة

`public.tenant_scoped_probe` جدول اختبار عادي داخل PostgreSQL 17، وليس جدول إنتاج
أو مهاجرة أو جدولًا مؤقتًا محصورًا في اتصال واحد. تنشئه fixture بدور `sahl_migrator`
كي تصل إليه اتصالات `sahl_app` الفعلية.

العقد: مالكه `sahl_migrator`، و`tenant_id UUID NOT NULL`، ومعرّف ونص payload بسيطان.
لا تسلسل أو نوع مخصص أو دالة اختبار دائمة. الاختبار يمنح التطبيق CRUD الضروري على
هذا الجدول وحده. الإنشاء والتهيئة إدارية؛ جميع محاولات الوصول في مصفوفة الهجوم بدور
`sahl_app`. تزرع fixture صفّي A وB قبل تفعيل FORCE، داخل معاملة إعداد واحدة؛ لا سياسة
تجاوز للمهاجر. ترفض fixture تبنّي جدول موجود مسبقًا، وتسقط فقط الجدول الذي أنشأته
بـ`DROP TABLE` دون CASCADE في teardown، فتزال سياسته ونوع صفه وكائناته التابعة.
يقارن اختبار lifecycle الكتالوج قبل التشغيل وبعده، في النجاح والاستثناء؛ لا بقاء لكائن اختبار.

### 3. عقد السياسة

داخل fixture، وبعد إنشاء الجدول:

```sql
ALTER TABLE public.tenant_scoped_probe ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_scoped_probe FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON public.tenant_scoped_probe
    FOR ALL TO sahl_app
    USING (tenant_id = app.current_tenant_id())
    WITH CHECK (tenant_id = app.current_tenant_id());

REVOKE ALL ON TABLE public.tenant_scoped_probe FROM PUBLIC, sahl_app;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON public.tenant_scoped_probe TO sahl_app;
```

تحدد `USING` الصفوف المقروءة والقابلة للتحديث والحذف؛ تفحص `WITH CHECK` القيم
الجديدة في INSERT وUPDATE. كلا التعبيرين صريح. إثبات رفض إدراج صف لـB أو نقل صف A
إلى B يتطلب رفض العملية من PostgreSQL، ثم إثبات عدم تغير البيانات؛ عدم ظهور الصف
في SELECT وحده لا يكفي.
[مرجع PostgreSQL 17 لـCREATE POLICY](https://www.postgresql.org/docs/17/sql-createpolicy.html).

السياسة الواحدة تستخدم الوضع الافتراضي `PERMISSIVE` وتعبيرًا ضيقًا. لا سياسة إضافية
توسّع الوصول، ولا `USING (true)`. كلمة «صارمة» هنا لا تعني `AS RESTRICTIVE` منفردة:
PostgreSQL يحتاج سياسة permissive مطابقة لإتاحة صف، ثم يطبق السياسات restrictive إن وجدت.
[تركيب سياسات PostgreSQL](https://www.postgresql.org/docs/17/sql-createpolicy.html).

### 4. الفشل المغلق وحدود الثقة

الغائب والفارغ والنص غير الصالح تقرؤه `app.current_tenant_id()` كـ`NULL`. لا يحقق
`tenant_id = NULL` شرط الإتاحة، فتكون القراءة بلا صفوف وUPDATE/DELETE بلا أثر.
الإدراج دون سياق أو بجهة أخرى مرفوض بـ`WITH CHECK`. لا fallback ولا lookup ولا حالة جهة
داخل السياسة. الرفض المبكر للسياق في الخدمة وHTTP يظل قائمًا أيضًا.

البرهان يفترض سياقًا يضبطه الحد الموثوق وفق ADR-0015؛ لا يدّعي أن إعداد PostgreSQL
يصادق الهوية أو يمنع من يملك بيانات اتصال runtime وSQL اعتباطيًا من تبديل ذلك الإعداد.
اختبارات SQL المباشر تثبت إنفاذ السياسة مع السياق المحدد، ولا تنشئ مسار HTTP يقبل جهة من العميل.

### 5. تهديد إعادة استعمال الاتصال

يُنشأ Engine اختبار حقيقي بـ`pool_size=1` و`max_overflow=0`، ويُثبت أن المعاملات
تعيد استعمال الاتصال نفسه بمطابقة `pg_backend_pid()`. بعد كل من commit وrollback والاستثناء تبدأ معاملة
بلا سياق: الدالة `NULL` وقراءة probe صفر صفوف. ثم تعمل A وبعدها B على الاتصال نفسه،
ولا ترى B صفوف A. الانتقال إلى اتصال آخر لا يثبت قبول هذا الشرط.

السياق transaction-local عبر `set_config(..., true)` وفق ADR-0015. A13 المعتمد يقيس
انتهاء المعاملة وعدم بقاء السياق؛ لا يضيف دعمًا أو سياسة جديدة للمعاملات المتداخلة.

### 6. عقد إضافة جدول مملوك لجهة وحارس الاكتمال

أي جدول أعمال مملوك لجهة يُضاف لاحقًا يجب أن يحمل `tenant_id UUID NOT NULL` وأن ينشئه
المهاجر مع `ENABLE` و`FORCE` وسياسة العزل ومنح runtime المحددة في المهاجرة نفسها.
يخضع لاختبارات SQL/ORM السلبية، ولا يعتمد على filters أو مراجعة اسم الجدول يدويًا.

يعتمد اكتشاف الجداول على وجود عمود `tenant_id` غير محذوف في كتالوج PostgreSQL،
للجداول العادية والمقسمة (`relkind r/p`) خارج مخططات النظام. لا قائمة أسماء ثابتة
تحدد كامل النطاق. يتحقق الحارس من UUID وNOT NULL والمالك، و`relrowsecurity`
و`relforcerowsecurity`، وسياسة واحدة PERMISSIVE للأمر ALL ولدور التطبيق وحده،
ومطابقة كل من `USING` و`WITH CHECK` لتعبير مساواة هوية الجهة. أي سياسة إضافية ترفض. الاختبارات السلبية للحارس
تثبت أنه يرفض إسقاط أحد هذه الشروط.

لا يدخل `public.tenants` في هذا الاكتشاف لأنه لا يحمل `tenant_id`. يحميه عقد مستقل:
لا عمود جهة، لا tenant RLS، ولا منح runtime. لا يُستثنى جدول جديد يحمل `tenant_id`
باسمه وحده. حراس الملكية والمنح والأدوار مكملة وفق ADR-0017.

## التحقق وإجراء الإغلاق

تعتمد مصفوفة A1–A13 وترقيمها في §10 من [خطة Phase 2A](../phase-2a.md).
مصادر التنفيذ والإثبات في `apps/api/tests/db/`: ‏`rls_probe.py` و`rls_catalog.py`،
واختبارات `test_rls_attack_matrix.py` و`test_rls_pool_reuse.py`
و`test_rls_catalog.py` و`test_rls_fixture_lifecycle.py`
و[test_rls_runtime_ddl_denial.py](../../apps/api/tests/db/test_rls_runtime_ddl_denial.py).
يثبت اختبار DDL رفض runtime لتغيير الجدول أو السياسة أو إسقاطهما.

نجح Backend كاملًا: **222 passed** مع `--strict-security-gates`؛ 153 اختبارًا سابقًا
و69 جديدًا. الجديدة 53 على PostgreSQL الفعلي (25 للمصفوفة، 15 للكتالوج، 4 للـpool،
7 لرفض DDL، 2 لدورة fixture) و16 وحدة (7 لتطبيع التعبير، 5 للنمط الصارم، 4 لعقود البوابات).
التفصيل في §14 من خطة Phase 2A. نجح حارس القاعدة بعد pytest: لا آثار probe وصفر جداول
إنتاج مملوكة لجهة. نجحت 25 حالة PowerShell لتنسيق تشغيل البوابات بصورة مستقلة.

تشغّل البوابات pytest مع `--strict-security-gates`، فيرفض نتائج SKIP وXFAIL وXPASS الفعلية.
يعمل `python -m tests.db.verify_clean_database` بعد pytest محليًا حتى عند فشله،
وفي CI بخطوة `if: always()`. كل إخلال بالنظافة أو عقد الكتالوج blocking.
لا continue-on-error أو SQLite أو mocks بديلة للقاعدة. يبقى PostgreSQL 17 service القائم
في CI؛ لا ملفات Docker أو بنية تشغيل جديدة في هذه المجموعة.

إجراء الإغلاق هو تشغيل `03-test.ps1` بكامل 17 بوابة؛ يورد التقرير الختامي نتيجته
ومسار سجله ونتائج المصفوفة وWITH CHECK وSQL/ORM وpool reuse والتحقق المباشر من القاعدة.
لا تُستنتج نتيجة البوابة الشاملة من عدد Backend وحده. لم يُنفّذ CI بعيد للمجموعة الرابعة
عند تسجيل هذه النتيجة؛ أي تشغيل لاحق يحتاج run مثبتًا على commit معلوم.
القبول النهائي للمجموعة بيد المالك.

لا auth أو session أو JWT أو RBAC أو Authorization Service أو وحدات أعمال أو Phase 2B.
المجموعة الخامسة لا تبدأ دون اعتماد المالك.
