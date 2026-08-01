# Axel One

Axel One — full-stack приложение для управления календарём, задачами, целями, привычками, балансом и контекстным AI-помощником.

## Стек

- Frontend: React, TypeScript, Vite, адаптивный CSS.
- Backend: Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic.
- Данные: SQLite для локальной разработки, PostgreSQL 16 для production.
- Auth: Argon2, короткоживущий JWT access token, ротируемые и отзываемые refresh-сессии.
- AI: локальная Ollama или облачный GigaChat с обязательным явным согласием на передачу контекста.
- Production ingress: Caddy с автоматическим TLS и перенаправлением HTTP → HTTPS.

## Локальная разработка

Backend:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Для локального запуска оставьте:
# ENVIRONMENT=development
# DATABASE_URL=sqlite:///./axel.db
alembic upgrade head
uvicorn backend.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Frontend доступен на `http://localhost:5173`, API — на `http://localhost:8000`, Swagger — на `http://localhost:8000/docs`.

### Локальный Docker

Обычная команда запускает development-стек с PostgreSQL, console email и без secure-cookie:

```bash
docker compose up --build
```

Frontend будет доступен на `http://localhost:3000`, backend — на `http://localhost:8000`.
Файл `docker-compose.dev.yml` сохранён для обратной совместимости, но для стандартного локального запуска больше не требуется.

Если volume PostgreSQL был создан старой версией проекта с другим паролем, синхронизируйте пароль роли без удаления данных и повторите запуск:

```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v role_name="$POSTGRES_USER" -v new_password="$POSTGRES_PASSWORD" -f /opt/axel/sync-postgres-password.sql'
docker compose up -d
```

## Демо-данные

Приложение больше не создаёт публичный demo-аккаунт автоматически. Development seed запускается только явно.

В `.env`:

```dotenv
ENVIRONMENT=development
ENABLE_DEMO_SEED=true
DEMO_EMAIL=demo@example.test
DEMO_PASSWORD=уникальный-development-пароль-длиннее-12-символов
VITE_ENABLE_DEMO_LOGIN=true
```

После миграций:

```bash
python -m backend.database.seed
```

Seed идемпотентен: помеченные demo-записи синхронизируются относительно текущей даты, дубликаты не создаются, произвольные пользовательские записи не изменяются. Seed немедленно завершается ошибкой при `ENVIRONMENT=production`.

## Время и часовые пояса

- абсолютные моменты времени хранятся в UTC;
- backend использует timezone-aware `datetime`;
- naive datetime из HTML-форм интерпретируется в IANA timezone текущего пользователя и нормализуется в UTC;
- границы дня рассчитываются в timezone пользователя и корректно учитывают DST;
- API возвращает ISO 8601 со смещением;
- «сегодня», приветствие, календарь, задачи, привычки и аналитика не зависят от timezone сервера.

Миграция `20260728_0003` применяет следующее правило к legacy-данным:

- `events.start_at/end_at` и `tasks.due_at/reminder_at` интерпретируются как локальное время владельца записи;
- системные `created_at`, `updated_at` и `completed_at` интерпретируются как UTC.

Перед production-миграцией рекомендуется сделать резервную копию базы и проверить timezone пользователей.

## Authentication и email

Поддерживаются:

- регистрация и вход;
- ограничение попыток входа по IP и нормализованному email;
- подтверждение email одноразовой ссылкой;
- восстановление пароля одноразовой ссылкой;
- logout текущей сессии и всех устройств;
- ротация refresh-токена при каждом обновлении;
- отзыв всей семьи refresh-токенов при повторном использовании старого токена;
- отзыв всех сессий после смены или сброса пароля.

В базе хранятся SHA-256-хеши одноразовых идентификаторов и refresh JTI, а не пригодные для входа токены. В production refresh-токен передаётся только через host-only cookie с `HttpOnly`, `Secure`, `SameSite=Lax` и ограниченным path. Access token остаётся короткоживущим bearer-токеном.

Для разработки доступен `EMAIL_BACKEND=console`. Он запрещён startup-валидацией в production. Production требует:

```dotenv
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
EMAIL_FROM=Axel One <noreply@example.com>
```

Если SMTP использует логин, пароль обязателен. Не записывайте реальные одноразовые ссылки в production-логи.

In-memory rate limiter рассчитан на один backend worker. При нескольких репликах добавьте общий limiter на ingress/Redis; Caddy или внешний WAF должен быть дополнительным, а не единственным уровнем защиты.

## Экспорт, удаление и privacy

В настройках пользователь может:

- скачать JSON-экспорт собственных данных;
- повторно запросить подтверждение email;
- отозвать согласие на GigaChat;
- удалить аккаунт после ввода текущего пароля и строки `DELETE`.

Удаление отзывает сессии и удаляет связанные записи каскадно. Токены, хеш пароля и внутренние auth-сессии не включаются в экспорт.

Проект политики находится в [PRIVACY_POLICY.md](PRIVACY_POLICY.md) и отображается во frontend. До публичного запуска необходимо заполнить сведения об операторе, контакты, подрядчиков, сроки хранения и проверить документ у юриста.

При `LLM_PROVIDER=gigachat` сервер требует актуальное согласие версии `PRIVACY_POLICY_VERSION`. До согласия и после его отзыва запросы, передающие персональный контекст, возвращают `403`. В интерфейсе чекбокс согласия не установлен заранее.

## Production: домен и HTTPS

Полный пошаговый runbook для покупки домена, VPS, DNS, SMTP, production `.env`,
Docker/Caddy и smoke-тестов находится в [DEPLOYMENT.md](DEPLOYMENT.md).

### 1. DNS

Определите домен и создайте у DNS-провайдера:

- `A` запись: `DOMAIN` → публичный IPv4 сервера;
- `AAAA` запись: `DOMAIN` → публичный IPv6, только если он настроен;
- при необходимости `CNAME` для `www` → основной домен.

Откройте входящие TCP 80/443 и UDP 443. Порты PostgreSQL, backend и frontend наружу не публикуются.

### 2. Переменные окружения

Скопируйте `.env.example` в `.env` и задайте минимум:

```dotenv
ENVIRONMENT=production
DOMAIN=example.com
POSTGRES_PASSWORD=<уникальный случайный пароль>
SECRET_KEY=<openssl rand -hex 32>
CORS_ORIGINS=https://example.com
TRUSTED_HOSTS=example.com
USE_SECURE_AUTH_COOKIES=true
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.example.com
EMAIL_FROM=noreply@example.com
```

Если используется GigaChat:

```dotenv
LLM_PROVIDER=gigachat
LLM_MODEL=GigaChat-2
GIGACHAT_AUTHORIZATION_KEY=<секрет>
```

Startup-валидация блокирует production с дефолтным/коротким `SECRET_KEY`, SQLite, стандартным паролем PostgreSQL, localhost/wildcard CORS, demo seed, console email или небезопасными refresh cookies.

### 3. Запуск

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs backend caddy
```

Caddy использует `deploy/Caddyfile`, автоматически получает и обновляет TLS-сертификат, перенаправляет HTTP на HTTPS, добавляет HSTS и проксирует:

- `/api/*`, `/health`, `/docs`, `/openapi.json` → backend;
- остальные запросы → frontend.

Backend доверяет forwarded-заголовкам только от приватных Docker-сетей. Если перед Caddy добавляется CDN/load balancer, необходимо отдельно сузить доверенные proxy-сети и настроить сохранение исходного IP.

### 4. Проверка после deployment

```bash
curl -I http://example.com
curl -I https://example.com
curl https://example.com/health
```

Проверьте:

- HTTP отвечает redirect на HTTPS;
- сертификат соответствует домену;
- `Strict-Transport-Security` присутствует только на HTTPS production;
- регистрационное письмо и сброс пароля доставляются;
- refresh cookie имеет `HttpOnly`, `Secure`, `SameSite=Lax`;
- demo-аккаунт отсутствует;
- backup и restore PostgreSQL протестированы.

## Проверки

```bash
pytest backend/tests -q
cd frontend
npm test
npm run build
```

Тесты покрывают auth, ротацию/reuse refresh-токенов, rate limiting, одноразовые email-токены, отзыв сессий, UTC/DST, пользовательские границы дня, idempotent seed, экспорт/удаление, GigaChat consent, production validation и мобильную CSS-регрессию.

## Основные API-маршруты

| Область | Маршруты |
| --- | --- |
| Auth | `/auth/register`, `/login`, `/refresh`, `/logout`, `/logout-all` |
| Email/password | `/auth/forgot-password`, `/reset-password`, `/verify-email`, `/request-email-verification`, `/change-password` |
| Account | `GET /account/export`, `DELETE /account` |
| Consent | `GET/POST/DELETE /settings/ai-consent` |
| Calendar/tasks | `/events`, `/tasks` |
| Goals/habits | `/goals`, `/habits` |
| Analytics | `/dashboard`, `/analytics`, `/energy`, `/balance`, `/overload` |
| AI | `/ai/status`, `/ai/chat`, `/ai/conversations` |
