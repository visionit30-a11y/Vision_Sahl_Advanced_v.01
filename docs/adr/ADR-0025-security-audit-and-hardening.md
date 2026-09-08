# ADR-0025: Security Audit Events والتنقيح والبوابات الأمنية

- **الحالة:** G1 معتمدة؛ نُفذ عقد audit في G2 بموافقة صريحة. التنفيذ المرحلي والأدلة في [تقرير G2](../phase-2e-g2-verification.md).
- **التاريخ:** 2026-09-08.
- **الأساس:** `phase-2d-baseline` عند `1677d114c5736c4032b862ddf0b58517490d1317`.
- **العلاقة:** يكمل ADR-0022 ولا يغيّر Authentication أو TenantContext أو RLS أو RBAC أو UI Settings.

## 1. الواقع الذي بُني عليه القرار

توجد `auth.security_events` منذ migration 0009، وكتالوج من 11 نوعًا في
`app/models/auth_security.py`، و`SecurityEventWriter` في `app/auth/controls.py`.
تكتب دوال reset أحداثها داخل معاملة التغيير؛ ويربط auth HTTP أحداث logout وtenant switch
وmembership denial وCSRF throttling. وجود اسم في الكتالوج لا يثبت اكتمال جميع emitters.

الحقول الحالية ليست عقدًا مغلقًا كاملًا: نوع الحدث والنتيجة مقيدان في DB، لكن reason/correlation
ونطاق subject digest وروابط الهوية تحتاج قيودًا واختبارات إضافية. دالة الكتابة الحالية لا تثبت
وجود كل `user_id`، وقد تقبل ارتباط session/membership عند غياب user؛ إسقاط الرابط غير الصحيح
إلى NULL ليس بديلًا عن التحقق من الثقة ومنع تلف المعنى الأمني.

التنقيح الحالي يخفي بعض المفاتيح وvalidation input/ctx، ورسالة 500 عامة. لكنه لا يثبت أمان
كل stdout/stderr أو stdlib/Uvicorn أو SQLAlchemy أو رسائل validation وأسماء extra keys.
فحص الأسرار الحالي في CI يستهدف ملف `.env` الجذري؛ لا يثبت غياب الأسرار من التاريخ أو
بقية الملفات. لا يوجد حاليًا dependency vulnerability audit.

## 2. الحدود الثابتة

- PostgreSQL هو مخزن الأحداث الأمنية الدائم. لا Redis، ولا queue أو spool محلي بديل، ولا SIEM integration.
- سجل أمني محدود للهوية والتفويض وتغييرات الصلاحيات؛ لا audit للأعمال أو تتبع قيم UI Settings.
- لا endpoint لقراءة سجل كل الجهات، ولا Audit UI، ولا صلاحية Platform Admin عالمية جديدة.
- لا تغيير لسياسات RLS أو FORCE RLS أو `app.current_tenant_id()` أو `set_config(..., true)`.
- تبقى قرارات AuthorizationService وpermissions وعقود التحقق والهوية ثابتة؛ فشل audit الإلزامي يمنع commit للتغيير الأمني، ولا ينشئ مسار مصادقة بديلًا.
- لا login/reset delivery/MFA أو Business Modules جديدة لاستكمال أحداث لا توجد لها واجهة HTTP اليوم.
- المصدر الموثوق للهوية هو flow القائم؛ UUID أو selector أو header من العميل ليس دليلًا.

## 3. كتالوج الأحداث المركزي

يُقترح `SecurityEventType` typed مركزي واحد مع `SecurityEventResult` و`SecurityReasonCode`.
تبقى IDs القديمة ثابتة. يمنع النص الحر للنوع/السبب ونسخ قوائم runtime متباعدة؛ الاختبارات تقارن
الكتالوج مع قيود DB. لا يعاد كتابة migrations المنشورة؛ أي توسعة تحتاج migration لاحقة مستقلة.

| Event ID | النتيجة | نقطة الإصدار المطلوبة |
| --- | --- | --- |
| `login_success` | success | نجاح التحقق وإصدار session عبر الخدمة القائمة، قبل commit |
| `login_failure` | failure | نهاية محاولة المصادقة الفاشلة، بما فيها الحساب غير الموجود، دون enumeration |
| `logout` | success | إبطال الجلسة الحالية فعليًا |
| `session_revoked` | success | إبطال جلسة مفردة أو الأقدم عند حد التزامن؛ سبب محدود |
| `all_sessions_revoked` | success | عملية الإبطال الجماعي؛ لا حدث مضلل إن لم تتغير حالة |
| `password_changed` | success | تغيير credential فعلي؛ rehash تقني لا يعامل كتغيير كلمة مرور |
| `password_reset_requested` | success | طلب reset مقبول في مسار قائم؛ قبول الطلب لا يثبت وجود الحساب |
| `password_reset_completed` | success | استهلاك token وتغيير credential وإبطال الجلسات ذريًا |
| `membership_denied` | denied | فشل trusted membership resolution؛ لا تسجيل selector المزور |
| `tenant_switch` | success | تبديل العضوية مع bearer/CSRF rotation في العملية نفسها |
| `throttling_triggered` | denied | رفض عبر PostgreSQL throttle؛ scope/reason من enum |
| `authorization_denied` | denied | نقطة enforcement المركزية بعد قرار DENY؛ لا قرار بديل داخل audit |
| `csrf_rejected` | denied | طلب unsafe مرفوض بسبب missing/invalid/stale token؛ لا token أو digest |
| `origin_rejected` | denied | رفض Origin؛ سبب ثابت فقط، لا قيمة Origin الخام |
| `role_created` | success | نجاح إنشاء role ضمن الخدمة القائمة وTenantContext الحالي |
| `role_updated` | success | تحديث role قائم؛ لا الاسم أو before/after payload |
| `role_disabled` | success | تعطيل role فعلي |
| `role_permission_assigned` | success | ربط PermissionId مع role داخل الجهة |
| `role_permission_removed` | success | فك ربط PermissionId فعلي |
| `membership_role_assigned` | success | إسناد role إلى membership مثبتة داخل الجهة |
| `membership_role_removed` | success | فك إسناد فعلي |
| `security_events_pruned` | success | مهمة retention المحدودة؛ العدد فقط، دون IDs للصفوف المحذوفة |

الصفوف الأحد عشر الأولى موجودة في كتالوج baseline؛ بقية الصفوف توسعة مقترحة لا تعني تنفيذها.
تغطية النجاح عند mutations تعني حدثًا واحدًا لكل تغيير فعلي مع commit واحد، لا لكل retry أو
idempotent no-op. رفض إدارة role يسجل `authorization_denied` أو `membership_denied` بحسب
الحد الذي رفضه، ولا ينتج حدث نجاح. لا نسجل كل ALLOW أو كل قراءة إعدادات لتجنب تحويل السجل إلى
منصة تتبع. لا sampling للأحداث الإلزامية؛ عند وجود throttle لا ينفذ الطلب المرفوض العمل المحمي.

تحدد G2 mapping مغلقة لكل event/result/reason؛ الحد الأدنى للأسباب:
`invalid_credentials`, `membership_unavailable`, `permission_denied`,
`csrf_missing`, `csrf_invalid`, `csrf_stale`, `origin_denied`,
`csrf_bootstrap`, `concurrent_limit`, `logout`, `revoke_all`,
`password_reset`, `retention_expired`, `dependency_unavailable`.
هذه reason IDs داخلية، وليست رسائل HTTP أو channel لكشف الحسابات.

## 4. الحقول المسموحة فقط

لا JSON metadata مفتوحة ولا `details: Any` ولا serialization تلقائي لـrequest/exception/model.

| الحقل | القيد ومصدر الثقة |
| --- | --- |
| `id` | UUIDv7 يولده الخادم؛ لا client event ID |
| `created_at` | UTC timezone-aware من ساعة PostgreSQL؛ لا تاريخ يرسله العميل |
| `event_type` | عضو في الكتالوج typed؛ لا event نصي غير معروف |
| `result` | success/failure/denied مع mapping صحيحة لنوع الحدث |
| `reason_code` | NULL أو enum محدود مرتبط بالحدث؛ لا exception message |
| `correlation_id` | internal ID يولده الخادم؛ لا raw X-Request-ID |
| `user_id` | UUID مثبت من flow/DB؛ مستخدم مرتبط بالحدث، وليس إثباتًا بذاته لنجاح المصادقة |
| `session_id` | UUID لصف session مثبت مرتبط بالمستخدم؛ لا bearer أو digest |
| `membership_id` | العضوية المثبتة للسياق/المستخدم الحالي؛ لا selector أجنبي |
| `subject_digest` | اختياري؛ HMAC-SHA-256 فقط لمعرّف محاولة مجهولة أو IP عند الحاجة |

في login/reset لا يعني `user_id` أن صاحب الحساب هو actor مصادق عليه؛ معنى النوع والنتيجة
يحكم التفسير. في إدارة الصلاحيات يكون المستخدم والعضوية هما actor المثبت من principal الحالي.
الحساب غير الموجود لا ينتج UUID مختلقًا ولا استجابة مختلفة.

التوسعات المقترحة المحدودة عند تنفيذ كتالوج الإدارة/retention:
`role_id` و`target_membership_id` كـUUIDs ثبتت ملكيتها للجهة داخل العملية القائمة تحت RLS،
و`permission_id` من PermissionId الحالي فقط، و`affected_count` عدد صحيح غير سالب خاص بالتنظيف.
لا role names أو permission lists كاملة. روابط الطرفين يجب أن تطابق TenantContext الحالي؛
وجود UUID في DB وحده لا يكفي. لا يضاف `tenant_id` إلى هذا السجل العالمي، حفاظًا على ADR-0022.

عند استعمال `subject_digest` يلزم عقد مرافق لـ`subject_kind` و`subject_key_id` وdigest بطول
32 byte؛ لا HMAC قبل اعتماد purpose/key ID والمفتاح المستقل. القيمة الخام لا تسجل قبل hashing
أو بعده. هذه pseudonymous data وليست بيانات مجهولة الهوية. الصفوف القديمة ذات metadata ناقصة
تظل legacy غير موثوقة لهذا الغرض؛ لا نستنتج غرضًا أو مفتاحًا غير محفوظ، ولا نمحو التاريخ لتجميله.

الحقول الاختيارية غير المعروفة ترفض؛ لا تحوّل إلى نص ولا تُخفى فقط بكلمة replacement.
الـwriter يأخذ trusted result/typed contract داخليًا، ولا يعرض raw ID builder للـroutes.
يختبر DB writer وجود العلاقات واتساقها ويرفض التناقض، بدل قبول user وهمي أو روابط غير متسقة.

## 5. الحقول والمحتوى المحظور

محظور في security events وapplication/access/error logs وCI outputs/artifacts:

- passwords وpassword hashes/PHC، حتى بعد فشل التحقق.
- session bearer وsession digest وreset token/digest وCSRF token/digest.
- Cookie/Set-Cookie وAuthorization وheaders الخام وrequest/response bodies.
- HMAC/signing/API keys وDB/Redis credentials وDSNs وconnection URLs وبيانات Settings الكاملة.
- SQL statement/parameters وdriver exception text وexception args/locals/raw traceback.
- email/username/IP/User-Agent/Origin/Referer الخام، وURL/path/query غير المنقح.
- قيم UI Settings، role names، نصوص المستخدم، أسماء extra keys، أو روابط موارد لم تثبت ملكيتها.

Masking بالمفاتيح دفاع إضافي؛ الأساس allowlist قبل emission وبعد أي formatting.
لا يكفي إخفاء token بنجمة داخل report قد يحمل نسخته في Match/context/message.
لا استثناء لسر حقيقي في scanner ولا نشر لقيمته عند الإبلاغ عنه.

## 6. وحدة الكتابة والذرية والفشل

1. واجهة typed مركزية واحدة للأحداث؛ يمكن أن تستخدم دوال DB القائمة بدل تكرار إدراج الصفوف.
2. في عمليات التغيير القائمة، يسجل الحدث على **نفس connection والمعاملة**؛ فشل الحدث يلغي
   التغيير. لا transaction مستقلة بعد نجاح commit، ولا outbox جديد في هذه المرحلة.
3. عمليات RBAC تظل داخل `tenant_transaction()` وتحت RLS؛ لا يقرأ audit writer جداول tenant
   عبر مسار عام، ولا ينشئ أو يغير TenantContext.
4. لرفض/فشل لا يغيّر حالة أمنية، يكتب الحدث في معاملة قصيرة بعد rollback المطلوب، حتى لا يختفي
   مع الاستثناء. عند تعذر DB يبقى الرفض قائمًا؛ لا ALLOW أو session ناجحة بسبب فشل audit.
5. عند فشل durable audit لا يدّعي النظام نجاح التسجيل؛ diagnostic ثابت محدود مثل
   `audit_write_failed` مع internal correlation ID فقط، دون error text أو أسرار. لا recursion
   إلى audit writer الفاشل، ولا retry غير محدود أو in-memory/Redis fallback.
6. event failure عند عملية إلزامية يرجع الخطأ العام الموافق للعقد؛ لا account enumeration،
   ولا 2xx لتغيير لم يثبت. تنقيح الأخطاء ليس بديلًا عن rollback أو security enforcement.

## 7. الملكية وappend-only وretention

`auth.security_events` تبقى **identity-security exception محددة قائمة**، بلا tenant RLS،
ولا يصبح مخطط auth كله مستثنى. لا تعديل لتصنيف أو سياسات أي جدول tenant.

- owner = `sahl_migrator`؛ `sahl_app` لا يملك objects ولا direct SELECT/INSERT/UPDATE/DELETE/TRUNCATE.
- الكتابة عبر EXECUTE لتوقيعات محددة فقط؛ SECURITY DEFINER القائمة/اللازمة مملوكة للمهاجر،
  `search_path=pg_catalog` مثبت، بلا dynamic SQL أو PUBLIC EXECUTE أو ضبط tenant context.
- التطبيق append-only؛ لا محو/تعديل روتيني، ولا تعديل cascade يمحو الحدث عند حذف user/session.
- لا ادعاء tamper-proof أمام DB owner/superuser؛ لا hash chain أو توقيع أو WORM في هذه المرحلة.
- قراءة التحقيق ليست HTTP/Platform Admin API؛ تحتاج عملية تشغيل محدودة ومصرحًا بها مستقبلًا.

**اقتراح retention لاعتماد G1:** تثبيت 90 يومًا للأحداث، كما في ADR-0022، من `created_at`.
مهمة يومية bounded/idempotent تحذف ما انتهت مدته فقط؛ لا caller-supplied cutoff يتجاوز السياسة.
التأخر في التشغيل يُكشف ولا يُسمى التزامًا بالاحتفاظ. لا تنفيذ cleanup في G1.

اقتراح G2/G4 اللاحق: capability صيانة منفصلة عن runtime، بلا ownership/BYPASSRLS أو grants
حذف عامة، تنفذ دالة purge محدودة مملوكة للمهاجر على جدول الأحداث فقط. يمكن اقتراح دور
`sahl_security_maintenance` لهذا EXECUTE وحده؛ يتطلب قبول تصميم G2 قبل إنشائه.
الأداة ليست endpoint، وتستخدم batches وحدًا أقصى واختبار تزامن؛ تسجل
`security_events_pruned` مع count في معاملة الحذف نفسها. فشل الحدث يلغي الحذف.

TTL لبقية جداول المصادقة لا يتغير. لا حذف من قاعدة التطوير أو production لإثبات الاختبار؛
تختبر الصيانة على PostgreSQL disposable فقط. اقتراح النسخ الاحتياطية rolling retention
بحد أقصى 30 يومًا مع purge قبل إتاحة restore؛ ليس وصفًا للبنية الحالية ولا ادعاء محو بعد 90
يومًا. اعتماد سياسة النسخ الفعلية وصلاحية الصيانة شرط تشغيلي قبل إعلان تطبيق retention في
production، وليس مانعًا لكتابة G1 أو لاختبارات DB المعزولة.

## 8. عقد error / validation / exception redaction

- تبقى envelopes وcodes و401/403/404/409 وno-store الحالية؛ تغيّر projection الداخلية فقط.
- رسائل AppError/HTTPException تأتي من catalog ثابت؛ لا `str(detail)` أو arbitrary details.
- validation يسمح بنوع خطأ معروف ومسار حقول schema معروف فقط؛ يحذف input/ctx والقيم وأسماء
  extra keys والرسائل القادمة من validator/driver. أخطاء malformed JSON لا تعيد body fragment.
- request path يسجل route template من router أو `unmatched`، لا المسار الخام أو query.
- internal audit/log correlation يولده الخادم. يبقى HTTP X-Request-ID compatibility منفصلًا؛
  القيمة التي يرسلها العميل ليست حقلًا موثوقًا ولا تسجل/تدخل audit. لا تغيير echo contract في G1.
- emission policy واحدة لـstructlog وstdlib وUvicorn؛ لا يسمح exception formatting بإعادة النص
  الحساس بعد redaction. يسمح فقط بـerror code/class معروفة ومواقع كود ثابتة دون مصدر/locals/args.
- `hide_parameters=True` مع SQL echo/debug مغلق، وDSNs محجوبة من repr. هذه طبقات دفاع لا تعفي
  من منع SQL/driver text ومن فحص stderr الحقيقي بعد re-raise.
- تنظيف correlation/context في finally لجميع النتائج والتزامن؛ لا انتقال بيانات طلب إلى آخر.
- PostgreSQL server statement/parameter logging وreverse-proxy access logs تحتاج إعداد تشغيل
  محدد يمنع النص/القيم الحساسة. لا ادعاء «لا أسرار» لخادم فعلي قبل فحص إعداداته ومخرجاته؛
  يثبت الاختبار المعزول ذلك ويقدم runbook محدودًا، دون تغيير إعداد DB مشتركة أو بناء منصة logs.

## 9. المراجع وحدود الادعاء

يوصي OWASP بمعالجة بيانات حدود الثقة باعتبارها غير موثوقة، وتقييد الوصول إلى السجلات والتحقق
من عدم تسريب البيانات الحساسة. خيارات العقد أعلاه قرارات المشروع، وليست ادعاء امتثال قانوني.
[OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).

يدعم SQLAlchemy إخفاء bind parameters؛ هذا لا يضمن أن driver أو custom logger لن يسرب نصًا،
لذلك يلزم اختبار الإخراج النهائي. [SQLAlchemy — Hiding Parameters](https://docs.sqlalchemy.org/en/20/core/engines.html#hiding-parameters).

خطة CI والاعتماد المرحلي في [phase-2e.md](../phase-2e.md)، والقبول في
[phase-2e-exit-criteria.md](../phase-2e-exit-criteria.md). لا تسجل هذه الوثائق أي gate تنفيذية
جديدة PASS قبل تشغيلها في المجموعة المصرح بها.
