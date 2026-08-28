# Production-развёртывание Axel One

Эта инструкция рассчитана на один VPS с Ubuntu 24.04/22.04, публичным IPv4,
PostgreSQL в Docker Compose и Caddy в роли HTTPS reverse proxy.

## 1. Что нужно подготовить

- домен или поддомен, например `app.example.com`;
- VPS с публичным IPv4, минимум 2 CPU, 4 GB RAM и 30 GB SSD;
- SSH-доступ к VPS по ключу;
- SMTP-аккаунт для отправки писем;
- действующий ключ GigaChat;
- отдельный email, на котором можно проверить регистрацию и сброс пароля.

Не размещайте PostgreSQL на публичном порту и не сохраняйте `.env` в Git.

## 2. Купить домен

1. Выберите регистратора доменов.
2. Найдите свободное имя и оформите его на владельца проекта.
3. Включите двухфакторную аутентификацию в аккаунте регистратора.
4. Включите автоматическое продление домена.
5. Решите, какой адрес будет основным:
   - `example.com` — основной домен;
   - `app.example.com` — поддомен приложения.

В дальнейших командах заменяйте `app.example.com` своим адресом.

## 3. Заказать VPS

Выберите VPS с Ubuntu 24.04 LTS или 22.04 LTS. После создания сохраните:

- публичный IPv4;
- SSH-пользователя;
- путь к приватному SSH-ключу.

Проверьте вход:

```bash
ssh USER@SERVER_IP
```

Обновите сервер:

```bash
sudo apt update
sudo apt upgrade -y
sudo timedatectl set-timezone UTC
```

## 4. Настроить DNS

В DNS-панели домена создайте запись:

| Тип | Имя | Значение |
| --- | --- | --- |
| `A` | `app` или `@` | публичный IPv4 VPS |

Создавайте `AAAA` только при наличии реально настроенного публичного IPv6.
Неверная `AAAA`-запись может помешать выпуску TLS-сертификата.

Проверьте DNS:

```bash
dig +short A app.example.com
```

Команда должна вернуть IP вашего VPS.

## 5. Открыть только необходимые порты

На уровне firewall хостинг-провайдера разрешите:

- TCP 22 — SSH, желательно только со своего IP;
- TCP 80 — HTTP и выпуск сертификата;
- TCP 443 — HTTPS;
- UDP 443 — HTTP/3, необязательно.

PostgreSQL 5432, backend 8000 и frontend 3000 наружу открывать не нужно.

Если используется UFW:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
sudo ufw status
```

Учитывайте, что опубликованные Docker-порты могут обходить часть правил UFW.
Production Compose публикует наружу только порты Caddy.

## 6. Установить Docker

Используйте официальный APT-репозиторий Docker:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

Добавьте репозиторий:

```bash
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
```

Установите Docker Engine и Compose:

```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

Команды проекта можно выполнять через `sudo docker`. Добавление пользователя в
группу `docker` фактически даёт ему root-доступ и должно быть осознанным решением.

## 7. Загрузить проект на сервер

Рекомендуемый вариант — закрытый Git-репозиторий:

```bash
sudo mkdir -p /opt/axel-one
sudo chown "$USER":"$USER" /opt/axel-one
git clone URL_РЕПОЗИТОРИЯ /opt/axel-one
cd /opt/axel-one
```

Если Git-репозитория нет, выполните с локального Mac:

```bash
rsync -av \
  --exclude .env \
  --exclude .venv \
  --exclude frontend/node_modules \
  --exclude frontend/dist \
  /Users/siuxin_yaroslav/Desktop/py_projects/ai_helper_for_life_manager/ \
  USER@SERVER_IP:/opt/axel-one/
```

## 8. Получить SMTP-доступ

У SMTP-провайдера получите:

- адрес сервера, например `smtp.provider.example`;
- порт `587` с STARTTLS;
- логин;
- SMTP-пароль или app password;
- разрешённый адрес отправителя.

Для лучшей доставляемости настройте в DNS записи SPF, DKIM и DMARC, которые
предоставляет почтовый провайдер. Адрес `EMAIL_FROM` должен быть разрешён
провайдером.

## 9. Создать production `.env`

На сервере:

```bash
cd /opt/axel-one
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
openssl rand -hex 24
```

Первый результат используйте как `SECRET_KEY`, второй — как
`POSTGRES_PASSWORD`. Отредактируйте `.env`:

```dotenv
ENVIRONMENT=production
DOMAIN=app.example.com

POSTGRES_DB=axel
POSTGRES_USER=axel
POSTGRES_PASSWORD=ВСТАВЬТЕ_СЛУЧАЙНЫЙ_ПАРОЛЬ_БД

SECRET_KEY=ВСТАВЬТЕ_СЛУЧАЙНЫЙ_SECRET_KEY
ACCESS_TOKEN_MINUTES=30
REFRESH_TOKEN_DAYS=30

CORS_ORIGINS=https://app.example.com
TRUSTED_HOSTS=app.example.com
TRUSTED_PROXIES=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16

USE_SECURE_AUTH_COOKIES=true
REFRESH_COOKIE_NAME=axel_refresh
REFRESH_COOKIE_SAMESITE=lax

EMAIL_BACKEND=smtp
SMTP_HOST=smtp.provider.example
SMTP_PORT=587
SMTP_USERNAME=SMTP_ЛОГИН
SMTP_PASSWORD=SMTP_ПАРОЛЬ
SMTP_USE_TLS=true
EMAIL_FROM=noreply@example.com

NOTIFICATION_WORKER_ENABLED=true
NOTIFICATION_POLL_INTERVAL_SECONDS=30
NOTIFICATION_SCHEDULE_HORIZON_HOURS=48
NOTIFICATION_RETRY_BASE_SECONDS=60
NOTIFICATION_RETRY_MAX_SECONDS=3600
NOTIFICATION_MAX_ATTEMPTS=5
NOTIFICATION_CLAIM_TIMEOUT_SECONDS=300
NOTIFICATION_BATCH_SIZE=20

ENABLE_DEMO_SEED=false
VITE_ENABLE_DEMO_LOGIN=false

LLM_PROVIDER=gigachat
LLM_MODEL=GigaChat-2
GIGACHAT_AUTHORIZATION_KEY=КЛЮЧ_GIGACHAT
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_VERIFY_SSL=true

PRIVACY_POLICY_VERSION=2026-08-17

# Сначала включайте только с credentials тестового магазина.
YOOKASSA_ENABLED=false
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RETURN_URL=https://app.example.com/billing/return
YOOKASSA_CURRENCY=RUB
YOOKASSA_CAPTURE=true
YOOKASSA_RECURRING_PAYMENTS_ENABLED=false
YOOKASSA_WEBHOOK_IP_CHECK_ENABLED=true
YOOKASSA_REQUEST_TIMEOUT_SECONDS=30
YOOKASSA_RECEIPT_MODE=disabled
YOOKASSA_VAT_CODE=
YOOKASSA_TAX_SYSTEM_CODE=
YOOKASSA_PAYMENT_SUBJECT=service
YOOKASSA_PAYMENT_MODE=full_payment
SUBSCRIPTION_GRACE_PERIOD_DAYS=3
SUBSCRIPTION_RETRY_DELAYS_HOURS=24,72
SUBSCRIPTION_WORKER_POLL_INTERVAL_SECONDS=300
SUBSCRIPTION_WORKER_BATCH_SIZE=20
EXECUTIVE_PLAN_ENABLED=true
```

Правила:

- в `DOMAIN` указывается имя без `https://` и без завершающего `/`;
- `CORS_ORIGINS` содержит полный HTTPS origin;
- не используйте значения из `.env.example` как production-секреты;
- не отправляйте `.env` в Git, мессенджеры или баг-трекер;
- при смене версии privacy policy обновляйте `PRIVACY_POLICY_VERSION`.
- секрет ЮKassa храните только в backend `.env`; переменных `VITE_YOOKASSA_*` в проекте быть не должно.

Проверьте права:

```bash
ls -l .env
```

Файл должен быть доступен только владельцу.

## 10. Проверить конфигурацию

```bash
cd /opt/axel-one
sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  config --quiet
```

Если отсутствует обязательная переменная, Compose завершится ошибкой. Backend
также блокирует production-запуск с небезопасными секретами, SQLite,
localhost-CORS, console email, отключённым notification worker или включённым demo seed.

## 11. Запустить production

DNS уже должен указывать на сервер, а порты 80/443 должны быть доступны.

```bash
sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d --build --wait --wait-timeout 180
```

Проверьте сервисы:

```bash
sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  ps

sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  logs --no-color --tail 200 backend caddy
```

Все сервисы должны работать, backend и frontend — иметь статус `healthy`.
Caddy автоматически получает сертификат и перенаправляет HTTP на HTTPS, если
DNS настроен верно и порты 80/443 доступны.

## 12. Проверить HTTPS

С локального компьютера:

```bash
curl -I http://app.example.com
curl -I https://app.example.com
curl https://app.example.com/health
```

Ожидаемый результат:

- HTTP перенаправляется на HTTPS;
- сертификат выпущен для выбранного домена;
- `/health` возвращает `"status":"ok"`;
- HTTPS-ответ содержит `Strict-Transport-Security`;
- браузер не показывает предупреждений о сертификате.

## 13. Проверить регистрацию и email

Используйте отдельный тестовый email:

1. Зарегистрируйтесь на `https://app.example.com`.
2. Убедитесь, что письмо подтверждения доставлено.
3. Проверьте, что ссылка ведёт на production-домен.
4. Подтвердите email и обновите профиль.
5. Выйдите и войдите снова.
6. Нажмите «Забыли пароль?».
7. Убедитесь, что ответ одинаков для существующего и неизвестного email.
8. Откройте письмо, установите новый пароль.
9. Проверьте, что старый пароль и старые сессии больше не работают.
10. Создайте событие и задачу с ближайшим напоминанием, дождитесь SMTP-письма и убедитесь, что в колокольчике появилась одна запись.
11. Проверьте ежедневный дайджест после `daily_digest_time` пользователя и отсутствие второго дайджеста в тот же локальный день.

В DevTools браузера проверьте refresh cookie:

- `HttpOnly`;
- `Secure`;
- `SameSite=Lax`;
- path `/api/v1/auth`.

## 14. Проверить GigaChat

1. Войдите подтверждённым тестовым аккаунтом.
2. Откройте AI-ассистента и проверьте статус провайдера.
3. Создайте тестовую цель.
4. Нажмите «Составить план».
5. Убедитесь, что перед первой отправкой появляется диалог согласия.
6. Прочитайте политику, установите чекбокс и подтвердите.
7. Дождитесь черновика плана.
8. Примените один выбранный пункт и проверьте созданную задачу или событие.
9. Отзовите согласие в настройках.
10. Убедитесь, что новый запрос к GigaChat снова требует согласия.

Не используйте реальные чувствительные данные во время smoke-теста.

## 15. Сделать backup PostgreSQL

Создайте каталог:

```bash
sudo mkdir -p /opt/axel-backups
sudo chmod 700 /opt/axel-backups
```

Создайте backup:

```bash
cd /opt/axel-one
sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "/opt/axel-backups/axel-$(date -u +%Y%m%d-%H%M%S).dump"
```

Настройте ежедневный запуск и хранение копий вне этого VPS. Backup считается
готовым только после успешной тестовой процедуры восстановления.

## 16. Обновление приложения

```bash
cd /opt/axel-one
git pull --ff-only
sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d --build --wait --wait-timeout 180
```

Перед обновлением базы создавайте backup. Миграции Alembic запускаются backend
контейнером после проверки production-конфигурации.

## 17. Диагностика

```bash
sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  ps

sudo docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  logs --no-color --tail 300 backend caddy db
```

Частые причины:

- Caddy не получает сертификат: DNS ещё не обновился, закрыты 80/443 или задана
  неверная `AAAA`-запись;
- backend не стартует: startup-валидация перечислит отсутствующие или
  небезопасные переменные;
- письма не приходят: неверные SMTP credentials, адрес отправителя не разрешён,
  отсутствуют SPF/DKIM/DMARC;
- GigaChat не отвечает: неверный authorization key, scope, SSL-настройки или
  исчерпаны лимиты провайдера.

## Критерий готовности

Production считается готовым, когда:

- домен открывается только по HTTPS;
- все контейнеры healthy;
- регистрация, подтверждение email и сброс пароля доставляют письма;
- refresh cookie защищена;
- GigaChat создаёт план только после явного согласия;
- demo seed выключен;
- backup создан и тестово восстановлен;
- политика конфиденциальности заполнена реальными реквизитами.

## 18. Настроить ЮKassa и проверить платежи

Интеграция в коде не означает готовность к реальным списаниям. До production-запуска владелец магазина должен завершить договорные, фискальные и кабинетные настройки и провести успешный тестовый платёж.

### 18.1. Создать и настроить магазин

1. Зарегистрируйте магазин в [личном кабинете ЮKassa](https://yookassa.ru/my/).
2. В разделе «Настройки — Магазин» скопируйте `shopId` тестового магазина.
3. В разделе «Интеграция — Ключи API» получите секретный ключ тестового магазина. Не отправляйте его в Git, frontend, логи или мессенджеры.
4. Запишите тестовые значения в закрытый `.env`, установите `YOOKASSA_ENABLED=true` и перезапустите backend.
5. Убедитесь, что `YOOKASSA_RETURN_URL=https://app.example.com/billing/return` открывается через текущий frontend. Return URL не является доказательством оплаты.

ЮKassa использует HTTP Basic Auth: `shopId` как username и secret key как password. Каждый POST получает Idempotence-Key не длиннее 64 символов. Axel One использует `checkout:<payment_id>` и `renewal:<subscription_id>:<period_start>` и при сетевом повторе сохраняет тот же ключ. См. [формат взаимодействия](https://yookassa.ru/developers/using-api/interaction-format).

### 18.2. Настроить HTTPS webhook

В разделе «Интеграция — HTTP-уведомления» укажите:

```text
https://app.example.com/api/v1/billing/yookassa/webhook
```

Включите события:

- `payment.succeeded`;
- `payment.canceled`;
- `payment.waiting_for_capture`;
- `refund.succeeded`.

Для Basic Auth webhook настраивается именно в кабинете, не через API. ЮKassa требует HTTPS и порт 443 либо 8443. Axel One отвечает `200` после успешно обработанного или уже обработанного уведомления. Подлинность проверяется по реальному IP с учётом `TRUSTED_PROXIES` и повторным `GET` объекта платежа в ЮKassa; список сетей взят из [официальной документации webhook](https://yookassa.ru/developers/using-api/webhooks). Не отключайте `YOOKASSA_WEBHOOK_IP_CHECK_ENABLED` в production. При CDN/load balancer добавьте только его реальные адреса в `TRUSTED_PROXIES`, иначе `X-Forwarded-For` не будет принят.

### 18.3. Выбрать законный режим чеков

Не переносите настройки НДС из примера без проверки статуса продавца, договора с ЮKassa и консультации бухгалтера/юриста.

- `YOOKASSA_RECEIPT_MODE=54fz`: Axel One добавляет `receipt.customer` и одну позицию услуги. Обязательны подтверждённые `YOOKASSA_VAT_CODE` и `YOOKASSA_TAX_SYSTEM_CODE`; subject/mode задаются явно.
- `YOOKASSA_RECEIPT_MODE=external`: чек формируется внешней системой; Axel One не отправляет `receipt` в запросе платежа.
- `YOOKASSA_RECEIPT_MODE=disabled`: Axel One не формирует чек. Используйте только если владелец документированно подтвердил, что чек в этом контуре не требуется или формируется отдельно.
- `self_employed`: legacy-значение, которое startup-валидация отклоняет. В [истории изменений ЮKassa](https://yookassa.ru/developers/using-api/changelog) указано прекращение сервиса чеков для самозанятых с 29 декабря 2025 года. Для Axel One как сервиса самозанятого требуется актуальная внешняя схема (например, согласованный процесс через «Мой налог»), а не автоматическое применение параметров 54-ФЗ.

Общие сведения о чеках: [официальная документация ЮKassa](https://yookassa.ru/developers/payment-acceptance/receipts/basics).

### 18.4. Провести тестовый платёж

1. Сделайте backup тестовой БД и примените `alembic upgrade head`.
2. Войдите новым пользователем: в разделе «Подписка» должен быть FREE.
3. Выберите PRO monthly. Проверьте в DevTools, что browser отправляет только `plan_code` и `billing_interval`, а ответ содержит внутренний `payment_id` и HTTPS `confirmation_url`.
4. Завершите оплату тестовыми данными из кабинета ЮKassa.
5. На `/billing/return` сначала допустим статус pending. Тариф должен включиться после серверной проверки статуса через API ЮKassa; штатно её запускает `payment.succeeded`, а user-scoped polling служит fallback при задержке webhook.
6. В БД проверьте одну запись `billing_payments`, одну обработанную запись `billing_webhook_events` и активную `user_subscriptions`. Не копируйте confirmation URL и provider payload в тикеты.
7. Повторно доставьте то же уведомление из кабинета: период не должен продвинуться второй раз.
8. Проведите отменённый тестовый платёж и убедитесь, что платный доступ не выдан.

### 18.5. Проверить автопродление и отмену

По умолчанию `YOOKASSA_RECURRING_PAYMENTS_ENABLED=false`: первый платёж не запрашивает сохранение карты, а доступ продаётся ровно на один период. Если отправить `save_payment_method=true` магазину без права на рекуррентные платежи, ЮKassa вернёт `403 forbidden`. Включайте флаг только после того, как менеджер ЮKassa подтвердил рекуррентные платежи для конкретного shopId. После включения автопродление использует только подтверждённый сохранённый `payment_method.id`; расписанием управляет Axel One, как требует [сценарий повторных платежей](https://yookassa.ru/developers/payment-acceptance/scenario-extensions/recurring-payments/pay-with-saved).

На staging:

1. Убедитесь, что у активной подписки сохранён непустой method ID и `current_period_end` timezone-aware UTC.
2. Сдвиньте период только в отдельной тестовой БД либо используйте специально созданную тестовую подписку.
3. Запустите один цикл `python -c 'from backend.billing.worker import run_subscription_cycle; print(run_subscription_cycle())'`.
4. Повторите цикл параллельно из двух процессов: уникальный renewal периода и условный claim не должны дать два списания.
5. Смоделируйте отменённый provider payment: статус станет `past_due`, пользователь получит outbox-уведомление, а доступ сохранится на `SUBSCRIPTION_GRACE_PERIOD_DAYS`.
6. Проверьте configured retry delays и перевод на FREE после их исчерпания.
7. Нажмите «Отменить автопродление»: доступ остаётся до `current_period_end`, нового платежа нет. Затем проверьте «Возобновить подписку» до даты окончания.

### 18.6. Перейти на production credentials

1. Завершите активацию настоящего магазина и согласуйте способы оплаты/автоплатежи/чеки.
2. Выпустите production secret key в кабинете и замените тестовый ключ только в защищённом `.env`/secret store.
3. Проверьте production shopId, HTTPS return URL и webhook URL.
4. Оставьте `YOOKASSA_RECURRING_PAYMENTS_ENABLED=false`, пока ЮKassa явно не подключит магазину рекуррентные платежи.
5. Выполните `docker compose ... config --quiet`, затем запустите backend. Startup остановится при пустом/тестовом ключе, HTTP return URL или несогласованной фискализации.
6. Проведите один контролируемый платёж минимально допустимого выбранного тарифа и сверку в кабинете, приложении и банковской выписке.

Production нельзя считать готовым, пока не подтверждены production shopId, события webhook, режим чеков и успешный тестовый платёж.

### 18.7. Безопасно ротировать secret key

1. Остановите создание новых платежей (`YOOKASSA_ENABLED=false`) в короткое согласованное окно; уже оплаченный доступ в БД не исчезает.
2. Выпустите новый ключ в кабинете, сохраните его в secret store и перезапустите backend.
3. Выполните безопасный `GET`/тестовый checkout и проверьте webhook.
4. Только после проверки отзовите старый ключ в кабинете.
5. Никогда не печатайте ключ командами, которые попадут в shell history или CI log.

### 18.8. Ручная сверка спорного платежа

1. Найдите внутренний платёж только по user-scoped admin/support-процессу и выпишите внутренний ID, provider payment ID, snapshot суммы/валюты/тарифа и timestamps. Не выгружайте реквизиты карты.
2. Получите объект платежа напрямую через API/кабинет ЮKassa и сравните ID, status, paid, amount, currency и metadata.
3. Проверьте `billing_webhook_events`: `failed` можно безопасно повторно доставить после устранения причины; `processed` не должен активировать период повторно.
4. Если данные не совпадают, не меняйте статус SQL-командой. Остановите автопродление конкретной подписки, сохраните аудит и разберите расхождение с поддержкой ЮKassa.
5. При полном возврате текущая политика Axel One сохраняет оплаченный доступ до конца периода и выключает следующее автопродление. Любое иное правило требует отдельного продуктового и юридического решения и новых тестов.
