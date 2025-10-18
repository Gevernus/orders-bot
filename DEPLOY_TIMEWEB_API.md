## Timeweb Cloud API: создание VPS и деплой orders-bot

Источники: [Timeweb Cloud API Docs](https://timeweb.cloud/api-docs)

### Базовый URL
- Рабочая база для запросов: `https://api.timeweb.cloud/api/v1`  
  Примечание: `https://api.timeweb.cloud/v1` отвечает 404. Проверено.

### Аутентификация
- Заголовок: `Authorization: Bearer <TIMEWEB_API_TOKEN>`
- Ответы могут содержать `response_id` для трассировки.

### Полезные эндпоинты (проверено)
- Список серверов: `GET /servers`
- Изображения (образы ОС): `GET /images` (может быть пусто в зависимости от аккаунта)
- Локации: `GET /locations` (может требовать дополнительных прав; 403 в некоторых аккаунтах)

Пример запросов:

```bash
# Загрузить токен (локально, если хранится в .env.automation)
export $(grep -v '^#' /Users/gever/GIT/SORA-2-BOT/.env.automation | xargs)

# Проверка доступности API
curl -i -H "Authorization: Bearer $TIMEWEB_API_TOKEN" \
  https://api.timeweb.cloud/api/v1/servers

# Список образов
curl -s -H "Authorization: Bearer $TIMEWEB_API_TOKEN" \
  https://api.timeweb.cloud/api/v1/images | jq
```

### Создание VPS (пример)

У Timeweb существуют преднастроенные тарифы/пресеты. В разных аккаунтах доступны разные `preset_id` и `os.id`. Так как публичных эндпоинтов для списка пресетов может не быть, рекомендовано создать сервер в панели и посмотреть его `os.id`, `location`, `preset_id` через `GET /servers`, а затем использовать эти значения в API-запросе.

Пример тела (значения примерные — ось Ubuntu 22.04 часто имеет id 79, локация `ru-1`/`nl-1` зависит от аккаунта):

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TIMEWEB_API_TOKEN" \
  -H "Content-Type: application/json" \
  https://api.timeweb.cloud/api/v1/servers \
  -d '{
    "name": "orders-bot",
    "comment": "Orders bot VPS",
    "preset_id": 1,
    "os_id": 79,
    "location": "ru-1"
  }'
```

Если вернулся 404/403, проверьте корректность `os_id`/`preset_id` и права токена. Для проверки доступных значений создайте VPS через веб‑панель, затем посмотрите его поля через:

```bash
curl -s -H "Authorization: Bearer $TIMEWEB_API_TOKEN" \
  https://api.timeweb.cloud/api/v1/servers | jq
```

### Деплой orders-bot на готовый VPS

Когда сервер создан и доступен по SSH:

```bash
# Скопировать проект и поднять контейнеры
/Users/gever/GIT/orders-bot/scripts/deploy_vps.sh \
  <VPS_HOST> <SSH_USER> \
  "$TELEGRAM_BOT_TOKEN" "92912383"

# Проверить логи
ssh <SSH_USER>@<VPS_HOST> docker logs -f orders-bot
```

### Тест через Telethon

```bash
cd /Users/gever/GIT/orders-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
TELEGRAM_API_ID=25292477 \
TELEGRAM_API_HASH=555aedc2f3b0e72a65fd5facafd95fa9 \
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN \
BOT_USERNAME=<username_бота> \
python scripts/telethon_test.py
```

### Замечания
- В ряде аккаунтов `GET /locations` может возвращать 403 — это не блокер для деплоя.
- Отсутствие `images` в списке — обычная ситуация, используйте `os_id` из уже созданного сервера.
- Если API для пресетов недоступен, выбирайте тариф в панели, затем воспроизводите через API со считанными полями.


