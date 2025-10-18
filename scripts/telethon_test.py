import asyncio
import os

from telethon import TelegramClient


API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


async def main() -> None:
    if not API_ID or not API_HASH or not BOT_TOKEN:
        raise SystemExit("TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN must be set")

    session_name = os.environ.get("TELETHON_SESSION", "telethon_test_session")
    async with TelegramClient(session_name, API_ID, API_HASH) as client:
        me = await client.get_me()
        print(f"Logged in as: {me.username or me.id}")

        # Send /start to the bot and print response
        bot_username = os.environ.get("BOT_USERNAME")
        if not bot_username:
            # fallback to resolve by token (not always possible); otherwise ask user to provide username
            print("Set BOT_USERNAME to your bot handle, e.g., my_bot")
            return

        await client.send_message(bot_username, "/start")
        print("Sent /start to bot. Check conversation in Telegram.")


if __name__ == "__main__":
    asyncio.run(main())


