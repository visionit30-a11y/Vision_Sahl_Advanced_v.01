# ADR-0021: Cookies وCSRF وحدود محاولات المصادقة

- **الحالة:** معتمد للتنفيذ في Phase 2B — Group 1
- **التاريخ:** 2026-09-07
- **المرحلة:** Phase 2B

## Cookie وHTTPS

اسم cookie هو `__Host-sahl_session` وخصائصها `Secure; HttpOnly; SameSite=Lax; Path=/`
دون `Domain`. هي session cookie ولا تحتوي إلا bearer opaque. لا تخزن في localStorage أو
sessionStorage ولا يعتبر إغلاق المتصفح logout.

الإنتاج والتكامل واختبار المتصفح يعملون عبر HTTPS وsame-origin افتراضيًا. لا fallback غير
آمن في staging/production. يضيق CORS إلى origins وmethods وheaders المطلوبة مع credentials.

## CSRF

يعتمد المشروع synchronizer token لأن الجلسة خادمية. CSRF secret مستقل عن session bearer،
مرتبط بحالة الجلسة، يسترجع من response `Cache-Control: no-store` ويحفظ في ذاكرة العميل ثم
يرسل في `X-CSRF-Token`. لا يوضع في URL أو log أو storage دائم، ويقارن مقارنة آمنة.

Login وreset قبل المصادقة يستخدمان pre-auth CSRF challenge بعمر 10 دقائق وcookie opaque
منفصلة. تهدم عند نجاح login، وتولد جلسة جديدة؛ لا ترقية لحالة ما قبل المصادقة.

كل عملية unsafe تتطلب CSRF صحيحًا وOrigin موثوقًا قبل الأثر ويفضل قبل تحديث `last_seen`.
يسمح JSON فقط للمسارات المتحولة. SameSite وFetch Metadata دفاعان إضافيان، وليسا الإثبات
الوحيد.

## Throttling

تخزن الحصص في PostgreSQL atomic buckets مستقلة عن audit وtransaction المصادقة. لا Redis
ولا عداد ذاكرة محلية كمصدر حقيقة. مفاتيح البريد وIP تستخدم HMAC purpose-specific مع key ID؛
لا بريد أو IP خام في bucket.

| النطاق | الحد الابتدائي |
|---|---:|
| login / account selector | 10 خلال 15 دقيقة |
| login / IP | 30 خلال دقيقة |
| login / IP + account | 5 خلال 15 دقيقة |
| reset / selector | 3 خلال ساعة |
| reset / IP | 20 خلال ساعة |
| pre-auth CSRF / IP | 30 خلال دقيقة |

يحجز الطلب الحصة ذريًا قبل Argon2، وتبقى المحاولة محسوبة إذا فشلت المصادقة. لا قفل حساب
دائم يمكن استخدامه لتعطيل الضحية. `Retry-After` خشن وغير كاشف. فشل PostgreSQL يغلق المسار؛
لا fallback. لا يثق التطبيق بـ`X-Forwarded-For` إلا من proxy معتمد.

تحذف buckets بعد 48 ساعة من انتهاء أطول نافذة أو حظر. يثبت اختبار workers/اتصالات متعددة
أن عدد الحجوزات لا يتجاوز الحد.

## بوابة المتصفح

تضاف اختبارات متصفح حقيقي عند Group 7 لإثبات cookie flags وHTTPS وCORS وCSRF وتبديل الجهة
بين التبويبات. jsdom وHTTP unit tests لا يعتبران بديلًا عن هذا الدليل.
