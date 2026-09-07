# ADR-0022: أحداث المصادقة والخصوصية

- **الحالة:** معتمد للتنفيذ في Phase 2B — Group 1
- **التاريخ:** 2026-09-07
- **المرحلة:** Phase 2B

## القرار

ينشئ Phase 2B سجل أحداث أمن هوية محدودًا، لا Audit Platform للأعمال. الأحداث المطلوبة:

- login success/failure؛
- logout؛
- session revoked/all sessions revoked؛
- password changed؛
- password reset requested/completed؛
- membership denied؛
- tenant switch؛
- suspicious throttling event.

يحمل الحدث UUIDv7 ووقتًا ونوعًا ونتيجة وreason code محدودًا وcorrelation ID، وروابط مثبتة
للمستخدم أو session record أو العضوية عند معرفتها. لا يحمل `tenant_id`؛ يستعمل membership ID
المثبت عندما يحتاج سياق العلاقة. لا يسجل selector أجنبيًا كأنه علاقة موثوقة.

لا password أو hash أو session/reset/CSRF bearer أو Cookie أو Authorization أو request body
أو SQL parameters في الحدث أو application/access logs. IP يخزن HMAC عند الحاجة وUser-Agent
وصفًا خشنًا محدودًا، وكلاهما وفق retention المعتمد.

سجل التطبيق append-only: لا UPDATE أو DELETE روتينيًا لـ`sahl_app`. أحداث تغيير credential
أو session state تكتب في المعاملة نفسها، وتعذر الحدث يمنع اعتماد التغيير. failed-login events
لا تستبدل throttle buckets.

## الأخطاء والسجلات

قبل إدخال secrets، ينقح validation handler قيمة `input` وcontext الحساس مع إبقاء error
envelope. تعتمد السجلات allowlist للحقول، وredaction عميقًا كدفاع إضافي، وتمنع exception
formatting أو SQLAlchemy parameters من إعادة الأسرار. تختبر قيم canary عبر response وlogs
والاستثناءات وCI artifacts.

## الاحتفاظ

| البيانات | الاحتفاظ المبدئي |
|---|---:|
| sessions بعد الانتهاء/الإبطال | 30 يومًا |
| reset tokens بعد انتهاء حالتها | حتى 24 ساعة |
| CSRF challenges بعد الانتهاء | حتى ساعة |
| throttle buckets | 48 ساعة بعد انتهاء النافذة/الحظر |
| authentication security events | 90 يومًا |

users وmemberships بلا TTL؛ المحو والخصوصية سياسة مستقلة. التنظيف بأداة صيانة خارج HTTP
وبهوية تشغيل معتمدة، ولا يمنح التطبيق صلاحيات حذف عامة. يجب أن تغطي سياسة الحذف النسخ
الاحتياطية قبل الادعاء بالمحو الكامل.

## الحدود

لا بريد وإشعارات أو MFA rollout أو RBAC أو audit للأعمال في هذا القرار. مفاتيح HMAC أسرار
مستقلة ذات purpose وkey ID، ولا تلتزم في Git.
