## Orders Bot

Telegram bot to collect booking requests and manage order statuses. Uses SQLite for storage.

### Features
- Greeting + consent
- 4 platform buttons: Airbnb, Booking, Car rental, Tours
- Collect: Full name (EN), City, Dates, Main link, Backup link, Extra request, Promo code
- Admin commands: `/orders` to list last 10, inline buttons to change status

### Run locally (Docker)
```bash
export TELEGRAM_BOT_TOKEN=YOUR_TOKEN
export ADMIN_CHAT_IDS=111111,222222
docker compose up -d --build
```

### Deployment to VPS
```bash
./scripts/deploy_vps.sh <VPS_HOST> <SSH_USER> <BOT_TOKEN> <ADMIN_CHAT_IDS>
```

Data persists in `./data/orders.db` on the host.


