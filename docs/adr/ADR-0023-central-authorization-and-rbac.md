# ADR-0023: التفويض المركزي وRBAC دون تجاوز عزل الجهات

- **الحالة:** معتمد للتنفيذ في Phase 2C — Group 1
- **التاريخ:** 2026-09-07
- **المرحلة:** Phase 2C
- **المرجع:** ADR-0015 وADR-0016 وADR-0018، وBaseline `phase-2b-baseline`

## السياق

أثبتت Phase 2B المستخدم والجلسة والعضوية النشطة قبل إنشاء `TenantContext`. تحتاج المرحلة
التالية إلى تقرير ما إذا كان هذا المستخدم يستطيع تنفيذ فعل بعينه داخل الجهة المثبتة. إثبات
الهوية والعضوية لا يمنح صلاحية تلقائيًا، وإخفاء عنصر في الواجهة لا يحمي API أو قاعدة البيانات.

يجب ألا يكرر كل endpoint أو service تفسير الأدوار، وألا ينشئ التفويض طريقًا يلتف على
`tenant_transaction()` أو PostgreSQL RLS. وتبقى عقود Phase 2A و2B مقفلة.

## القرار

### 1. كتالوج Permission IDs

الصلاحية قدرة ذرية ثابتة، ومعرفها جزء من عقد backend العام. يوجد كتالوج مركزي واحد في
الكود، typed ومغلق بالمراجعة. لا تقبل الخدمة permission string حرة من HTTP أو قاعدة البيانات.

الصيغة:

```text
<scope>.<resource>.<action>
```

- أحرف ASCII صغيرة وأرقام وشرطة سفلية فقط داخل كل segment.
- `scope` هو `tenant` أو `platform`؛ ولا تستخدم `*` أو wildcard أو نفيًا ضمن المعرف.
- `resource` اسم جمع ثابت للمورد، و`action` فعل محدد مثل `read`, `create`, `update`,
  `delete`, `manage`؛ لا يعني `manage` ضمنيًا أي صلاحية أخرى إلا إذا عرّف الكتالوج ذلك صراحة.
- أمثلة عقدية غير منفذة في G1: `tenant.memberships.read`،
  `tenant.memberships.manage`، `tenant.roles.manage`، `platform.tenants.manage`.
- معرف منشور لا يعاد استخدامه بمعنى آخر. الحذف يكون deprecation ثم migration للبيانات قبل
  إزالته. تفشل البوابة إذا أشارت قاعدة البيانات إلى معرف غير موجود في الكتالوج.

لا يحتوي الكتالوج في G1 على صلاحيات Business Modules. تضاف صلاحيات كل module في مرحلته.

### 2. نموذج الأدوار

الدور حزمة صلاحيات، وليس proof للجهة ولا بديلًا عن العضوية:

```text
User
  -> active TenantMembership
  -> membership-role assignment in the same tenant
  -> tenant Role
  -> role-permission assignment
  -> catalogued Permission ID
```

- الدور tenant-scoped وله UUID ثابت واسم عرض قابل للتغيير. الاسم لا يشارك في قرار التفويض.
- الربط يستخدم IDs وقيود tenant المركبة. لا يمكن ربط عضوية أو دور من جهتين مختلفتين.
- لا توريث أدوار في Phase 2C، ولا deny rules أو wildcards. اتحاد الصلاحيات المسموحة للأدوار
  النشطة هو النتيجة؛ الغياب يعني الرفض.
- تعطيل الدور أو إزالة الربط يسري على قرار التفويض التالي. لا تحمل الجلسة snapshot طويل العمر
  للصلاحيات، ولا bearer claims أو JWT للصلاحيات.
- الأدوار النظامية، إن أضيفت، تعرف بمعرف role key ثابت في كتالوج مركزي وتدار كبذور migration.
  الخدمات لا تفحص role key أو اسم الدور؛ تمرر Permission ID إلى Authorization Service فقط.

### 3. خدمة التفويض الواحدة

واجهة التطبيق الوحيدة لاتخاذ القرار هي `AuthorizationService`. عقدها المنطقي:

```text
authorize(principal, tenant_context, permission_id, resource?) -> decision or denial
```

التدفق الإلزامي:

```text
validated server-side session
  -> AuthenticatedPrincipal
  -> unchanged TenantContext
  -> trusted Permission ID from the central catalog
  -> AuthorizationService
  -> tenant_transaction(TenantContext)
  -> role/permission lookup constrained by the same tenant
  -> allow or fail closed
  -> business operation in the same tenant boundary
  -> PostgreSQL RLS remains the final row-isolation control
```

- الـendpoint أو service يطلب قدرة، ولا يسأل عن اسم دور ولا يقرأ جداول RBAC مباشرة.
- `resource`، عند الحاجة إلى object-level authorization، selector فقط. تتحقق الخدمة من وجود
  المورد داخل `TenantContext` نفسه قبل القرار؛ لا تكشف الاستجابة هل ID أجنبي موجود.
- غياب principal أو context أو permission، أو فشل PostgreSQL، أو membership/role غير نشط،
  أو معرف غير معروف ينتج رفضًا مغلقًا.
- التفويض وRLS طبقتان متكاملتان: التفويض يقرر الفعل، وRLS يعزل الصف. نجاح إحداهما لا يعطل
  الأخرى، ولا تملك الخدمة `BYPASSRLS` أو اتصال المهاجر.
- منع الفحوص المتناثرة يطبق بحارس static يبحث عن role-name comparisons والوصول إلى نماذج
  RBAC خارج وحدتي authorization والمهاجرة والاختبارات المسموح بها.

### 4. العلاقة مع TenantContext

لا يضاف user أو role أو permission إلى `TenantContext`، ولا تتغير بنيته أو طريقة ضبط
`app.current_tenant_id()`. يبقى `AuthenticatedPrincipal` دليل actor والعضوية، ويبقى
`TenantContext` دليل الجهة. يحتاج قرار tenant permission الاثنين معًا، ويجب أن تتطابق
عضوية principal مع جهة السياق. لا ينشأ السياق من role أو permission أو resource ID.

### 5. تصنيف جداول Phase 2C

التصنيف المخطط لـG2؛ لا ينشئ G1 أي جدول:

| الجدول المخطط | التصنيف | عقد الحماية |
|---|---|---|
| `auth.roles` | tenant-owned | `tenant_id UUID NOT NULL` وENABLE + FORCE RLS وUSING + WITH CHECK |
| `auth.role_permissions` | tenant-owned | يحمل `tenant_id` صراحة، وRLS نفسه، وFK مركب يمنع ربط دور أجنبي |
| `auth.membership_roles` | tenant-owned | يحمل `tenant_id` صراحة، وRLS نفسه، وFKs مركبة تثبت تطابق جهة العضوية والدور |
| `auth.platform_role_assignments` | identity-security global exception | بلا `tenant_id`، لا RLS خاص بجهة، لا منح قراءة/كتابة مباشرة لـ`sahl_app`؛ وصول ضيق ومدقق فقط |

Permission IDs لا تحتاج جدول runtime مصدر حقيقة؛ الكتالوج typed في الكود. إذا احتاجت G2
قيود FK، يسمح بجدول catalog عالمي migration-managed، بلا منح كتابة runtime، وتبقى مطابقة
الكود والجدول بوابة فشل. يجب توثيق هذا الخيار قبل تطبيقه في migration.

لا يعفى مخطط `auth` ككل. كل جدول يحمل `tenant_id` يخضع حرفيًا لحارس ADR-0016. لا policy
واسعة ولا `USING (true)` ولا direct grants تتجاوز خدمة التفويض.

### 6. Platform Admin

`Platform Admin` actor عالمي مثبت بتعيين مستقل ومراجع، وليس tenant role ولا tenant وهمية.
صلاحياته تبدأ بـ`platform.*` ولا تمنحه تلقائيًا أي `tenant.*` أو قراءة صفوف الجهات.

عند الحاجة المستقبلية إلى عملية على بيانات جهة، يجب أن يحدد الطلب جهة صراحة، وتثبت خدمة
التفويض أولًا صلاحية platform المناسبة، ثم تنشئ الحدود الموثوقة `TenantContext` للجهة
المقصودة دون تعديل نوعه، وتنفذ العملية عبر `tenant_transaction()` ودور `sahl_app` المعتاد.
تظل ENABLE وFORCE RLS و`app.current_tenant_id()` فعالة. لا `BYPASSRLS`، ولا اتصال migrator،
ولا تعطيل policy، ولا loop عبر جميع الجهات في معاملة بلا سياق. هذا المسار ليس منفذًا في G1.

### 7. تسجيل القرار والخصوصية

كل رفض يعود باستجابة موحدة لا تميز بين مورد مفقود ومورد في جهة أخرى وعدم الصلاحية. تسجل
الأحداث security decision IDs موثوقة فقط: actor المثبت، tenant المثبت، Permission ID من
الكتالوج، والنتيجة/السبب المصنف. لا يسجل selector مزور كمعرف مورد أو جهة مثبت.

## استراتيجية الاختبار الملزمة للمجموعات اللاحقة

1. **Catalog/contracts:** uniqueness والصيغة والثبات، ورفض unknown/wildcard IDs، ومنع role
   strings والفحوص المتناثرة.
2. **Role graph:** اتحاد الصلاحيات، غيابها يرفض، الدور المعطل، إزالة assignment، وعدم وجود
   توريث ضمني أو صلاحية من role name.
3. **Tenant binding:** عضوية ودور وصلاحية من الجهة نفسها تنجح؛ كل توليفة cross-tenant في
   FKs أو service ترفض، مع بقاء RLS وFORCE guards خضراء.
4. **IDOR matrix:** لكل read/create/update/delete endpoint مستقبلي: ID صحيح من A، ID موجود
   في B، UUID مزور، مورد محذوف، وتبديل selector في path/query/body. حالات B والمزورة تعطي
   استجابة غير كاشفة واحدة ولا تغير بيانات.
5. **Defense in depth:** تجاوز Authorization Service مباشرة في SQL/ORM يظل محصورًا بـRLS؛
   ونجاح authorization لا يسمح بصف B أو INSERT/UPDATE ينقل صفًا إلى B.
6. **Session and membership changes:** revoked session، suspended user/membership، stale
   membership version، وتبديل tenant تبطل القرار السابق ولا تستخدم cache قديمة.
7. **Platform admin:** صلاحية platform لا تمنح tenant read، وكل tenant operation تحتاج
   context محددًا وتبقى تحت RLS؛ runtime لا يملك BYPASSRLS أو ملكية الجداول.
8. **HTTP/frontend:** إخفاء الزر لا يدخل دليل القبول. طلب API يدوي دون permission يرفض، ولا
   تؤثر permission أو role يرسلها العميل في القرار.
9. **Concurrency/failure:** تغيير assignment المتزامن لا ينتج allow خارج transaction
   المعتمدة، وفشل PostgreSQL يفشل مغلقًا ولا يستعمل cache أو fallback.

تعمل اختبارات PostgreSQL بدور `sahl_app` الفعلي، وتبقى strict security gates بلا SKIP أو
mock بديل للسلوك الأمني.

## البدائل المرفوضة

- `if user.role == "admin"` أو decorators تحمل أسماء أدوار.
- قوائم permissions يرسلها frontend أو تخزن في browser/session bearer.
- cache أو Redis كمصدر حقيقة لقرار التفويض.
- منح Platform Admin دور قاعدة بيانات أو `BYPASSRLS` أو تعطيل FORCE RLS.
- اعتبار membership أو TenantContext وحدهما إذنًا بالفعل.
- جداول tenant-scoped بلا `tenant_id` للتحايل على حارس RLS.

## النتائج

يصبح permission هو العقد الثابت، والدور مجرد تجميع tenant-scoped، والخدمة المركزية هي نقطة
القرار الوحيدة. تبقى PostgreSQL RLS مستقلة وفعالة كحد عزل نهائي، ولا تتغير عقود Phase 2A
أو 2B.
