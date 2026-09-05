# سجل التبعيات

كل مكتبة هنا معتمدة صراحة. لا تُضاف مكتبة جديدة ذات أثر معماري دون موافقة مالك المشروع،
ولا تُضاف مكتبة تؤدي دور طبقة مقفلة في الـ Stack.

## محظور دائمًا

Tailwind CSS · Bootstrap · أي إطار CSS Utility/Component بديل · Node.js كخلفية أو API أو
Jobs · Next.js/Angular/Vue · Django/Flask/NestJS · MySQL/SQLite/MongoDB كقاعدة تشغيل ·
أي Cache/Queue بديل عن Redis.

## الخلفية — Phase 0 (معتمد)

| المكتبة | الدور | المبرر |
|---|---|---|
| fastapi | إطار الـ API | TS-02 مقفل |
| uvicorn[standard] | خادم ASGI | تشغيل FastAPI محليًا وفي الحاويات |
| pydantic-settings | الإعدادات من متغيرات البيئة | TS-10: لا أسرار في الكود |
| SQLAlchemy 2.x | طبقة الوصول للبيانات | ADR-0005 |
| alembic | المهاجرات المتسلسلة | SRS §10 يوجب Migration لكل تغيير Schema |
| psycopg[binary] | مشغّل PostgreSQL | يدعم المتزامن وغير المتزامن بنفس عنوان الاتصال |
| redis | عميل Redis | TS-05 مقفل |
| structlog | Structured Logging | NFR-MO-01: وسوم correlation/tenant بلا بيانات حساسة |
| pytest · pytest-asyncio · httpx | الاختبارات | SRS §19 بند تعاقدي |
| ruff · mypy | Lint / Type check | بوابة خروج Phase 0 |

## الواجهة — Phase 0 (معتمد)

| المكتبة | الدور |
|---|---|
| react · react-dom | TS-01 مقفل |
| vite · @vitejs/plugin-react | أداة البناء المقفلة |
| typescript | لغة الواجهة المعتمدة رسميًا |
| eslint · prettier | Lint / Format |
| vitest · @testing-library/react | الاختبارات |

**توابع أدوات لازمة لتشغيل ما سبق** (بلا أثر معماري): `@eslint/js`,
`typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `globals`,
`jsdom`, `@testing-library/jest-dom`, `@types/react`, `@types/react-dom`, `@types/node`.

## معتمد مبدئيًا — يُثبَّت في المرحلة التي تحتاجه فعليًا

| المكتبة | المرحلة المتوقعة |
|---|---|
| react-i18next / i18next | Phase 1 |
| React Router | Phase 1 |
| TanStack Query | Phase 1 |
| TanStack Table (Headless — بلا CSS) | Phase 1 (محرك الجداول) |
| React Hook Form + Zod | Phase 1/2 |

أنماط معتمدة للواجهة: **CSS Modules + Design Tokens + CSS Variables**.
