import asyncio
import logging
import os
from typing import Dict, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .db import (
    init_db,
    insert_order,
    update_order_status,
    get_orders,
    assign_order_to_admin,
    get_waiting_orders,
    get_orders_by_admin,
)


# Conversation states
PLATFORM, FULL_NAME, CITY, DATES, MAIN_LINK, BACKUP_LINK, EXTRA_REQUEST, PROMO = range(8)


STATUSES: List[str] = [
    "В работе",
    "Ожидает верификации",
    "Ищем дропа",
    "Вторая попытка",
    "Третья попытка",
    "Готов",
    "Отменен",
    "Ожидает оплаты",
    "Оплачен",
    "Гость не приехал во время",
    "Проблемы с оплатой у гостя",
    "Нужно продление",
    "ВИП клиент",
]


PLATFORMS = [
    ("Airbnb", "airbnb"),
    ("Booking", "booking"),
    ("Прокат авто", "car_rental"),
    ("Экскурсии", "tours"),
]


ADMIN_CHAT_IDS = {
    int(cid) for cid in os.environ.get("ADMIN_CHAT_IDS", "").split(",") if cid.strip().isdigit()
}


def _platform_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text=title, callback_data=f"platform:{key}")]
            for title, key in PLATFORMS
        ]
    )


def _consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="Согласен и подписался", callback_data="consent_yes")]]
    )


def _status_keyboard(order_id: int) -> InlineKeyboardMarkup:
    rows = []
    for status in STATUSES:
        rows.append([InlineKeyboardButton(status, callback_data=f"status:{order_id}:{status}")])
    return InlineKeyboardMarkup(rows)


def _waiting_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Взять в работу", callback_data=f"take:{order_id}")]]
    )


def _my_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    # Статусы + отдельная кнопка "Закрыть"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(s, callback_data=f"status:{order_id}:{s}")] for s in STATUSES]
        + [[InlineKeyboardButton("Закрыть", callback_data=f"close:{order_id}")]]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logging.info("/start from user_id=%s chat_id=%s",
                 getattr(update.effective_user, "id", None),
                 getattr(update.effective_chat, "id", None))
    print(f"/start received: user_id={getattr(update.effective_user, 'id', None)}")
    text = (
        "Привет! Это бот заказов.\n\n"
        "Перед началом подтвердите согласие с правилами и подпишитесь на канал."
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=_consent_keyboard())
    else:
        await update.callback_query.message.reply_text(text, reply_markup=_consent_keyboard())
    return PLATFORM


async def on_consent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Выберите тип заказа:", reply_markup=_platform_keyboard())
    context.user_data["order"] = {}
    return PLATFORM


async def choose_platform(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, key = query.data.split(":", 1)
    context.user_data.setdefault("order", {})
    context.user_data["order"]["platform"] = key
    await query.edit_message_text("Укажите Имя и Фамилию гостя на английском:")
    return FULL_NAME


async def ask_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"]["full_name_en"] = update.message.text.strip()
    await update.message.reply_text("Укажите город:")
    return CITY


async def ask_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"]["city"] = update.message.text.strip()
    await update.message.reply_text("Укажите даты:")
    return DATES


async def ask_main_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"]["dates"] = update.message.text.strip()
    await update.message.reply_text("Ссылка на основной объект:")
    return MAIN_LINK


async def ask_backup_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["order"]["main_link"] = update.message.text.strip()
    await update.message.reply_text("Ссылка на запасной объект (можно пропустить, отправьте -):")
    return BACKUP_LINK


async def ask_extra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["order"]["backup_link"] = "" if text == "-" else text
    await update.message.reply_text("Дополнительный запрос (можно пропустить, отправьте -):")
    return EXTRA_REQUEST


async def ask_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["order"]["extra_request"] = "" if text == "-" else text
    await update.message.reply_text("Промокод (можно пропустить, отправьте -):")
    return PROMO


async def finalize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["order"]["promo_code"] = "" if text == "-" else text

    order: Dict[str, str] = context.user_data["order"]
    order["user_id"] = update.effective_user.id
    order["status"] = "В работе"
    order_id = insert_order(order)

    summary = (
        f"Заказ №{order_id} сохранен.\n\n"
        f"Платформа: {order['platform']}\n"
        f"Имя (EN): {order['full_name_en']}\n"
        f"Город: {order['city']}\n"
        f"Даты: {order['dates']}\n"
        f"Основной объект: {order.get('main_link','')}\n"
        f"Запасной объект: {order.get('backup_link','')}\n"
        f"Доп. запрос: {order.get('extra_request','')}\n"
        f"Промокод: {order.get('promo_code','')}\n"
        f"Статус: В работе"
    )
    await update.message.reply_text(summary)

    if ADMIN_CHAT_IDS:
        for admin_id in ADMIN_CHAT_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"Новый заказ №{order_id}\n"
                        f"От пользователя: {update.effective_user.id}\n\n"
                        + summary
                    ),
                    reply_markup=_status_keyboard(order_id),
                )
            except Exception:
                # Ignore admin notification failures
                pass

    return ConversationHandler.END


async def list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_CHAT_IDS:
        await update.message.reply_text("Доступ запрещен.")
        return
    rows = get_orders(limit=10, include_closed=False)
    if not rows:
        await update.message.reply_text("Заказов нет.")
        return
    for row in rows:
        text = (
            f"№{row['id']} | {row['platform']} | {row['full_name_en']} | {row['status']}\n"
            f"Город: {row['city']} | Даты: {row['dates']}\n"
            f"Осн.: {row['main_link']}\nЗап.: {row['backup_link']}\n"
        )
        await update.message.reply_text(text, reply_markup=_status_keyboard(int(row["id"])))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_admin = update.effective_user.id in ADMIN_CHAT_IDS
    if is_admin:
        text = (
            "Помощь (админ):\n"
            "- /orders_waiting — заказы без исполнителя\n"
            "- /work_on_orders — ваши активные заказы\n"
            "- /orders — последние 10 заказов со сменой статусов\n"
            "Нажмите ‘Взять в работу’ в /orders_waiting, далее меняйте статусы кнопками."
        )
    else:
        text = (
            "Помощь: отправьте /start, заполните анкету и дождитесь ответа админа.\n"
            "Если что-то пошло не так — повторите /start."
        )
    await update.message.reply_text(text)


async def orders_waiting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_CHAT_IDS:
        await update.message.reply_text("Доступ запрещен.")
        return
    rows = get_waiting_orders(limit=15)
    if not rows:
        await update.message.reply_text("Нет заказов в ожидании.")
        return
    for row in rows:
        text = (
            f"Ожидает №{row['id']} | {row['platform']} | {row['full_name_en']}\n"
            f"Город: {row['city']} | Даты: {row['dates']}\n"
        )
        await update.message.reply_text(text, reply_markup=_waiting_order_keyboard(int(row["id"])))


async def work_on_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_CHAT_IDS:
        await update.message.reply_text("Доступ запрещен.")
        return
    rows = get_orders_by_admin(update.effective_user.id, limit=15)
    if not rows:
        await update.message.reply_text("У вас нет заказов в работе.")
        return
    for row in rows:
        text = (
            f"В работе №{row['id']} | {row['platform']} | {row['full_name_en']} | {row['status']}\n"
            f"Город: {row['city']} | Даты: {row['dates']}\n"
        )
        await update.message.reply_text(text, reply_markup=_my_order_keyboard(int(row["id"])))


async def on_status_change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, order_id, status = query.data.split(":", 2)
    order_id_int = int(order_id)
    update_order_status(order_id_int, status)
    await query.edit_message_reply_markup(reply_markup=_status_keyboard(order_id_int))
    await query.message.reply_text(f"Статус заказа №{order_id} обновлен на: {status}")


async def on_take_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_CHAT_IDS:
        await update.callback_query.answer(text="Нет доступа", show_alert=True)
        return
    query = update.callback_query
    await query.answer()
    _, order_id_str = query.data.split(":", 1)
    order_id = int(order_id_str)
    assign_order_to_admin(order_id, update.effective_user.id)
    await query.edit_message_text("Заказ взят в работу.")


async def on_close_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in ADMIN_CHAT_IDS:
        await update.callback_query.answer(text="Нет доступа", show_alert=True)
        return
    query = update.callback_query
    await query.answer()
    _, order_id_str = query.data.split(":", 1)
    order_id = int(order_id_str)
    update_order_status(order_id, "Закрыт")
    await query.edit_message_text("Заказ закрыт.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Диалог отменен.")
    return ConversationHandler.END


def build_application() -> Application:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    init_db()
    application = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PLATFORM: [
                CallbackQueryHandler(on_consent, pattern="^consent_yes$")
            , CallbackQueryHandler(choose_platform, pattern="^platform:.")],
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_city)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_dates)],
            DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_main_link)],
            MAIN_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_backup_link)],
            BACKUP_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_extra)],
            EXTRA_REQUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_promo)],
            PROMO: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv)
    application.add_handler(CommandHandler("orders", list_orders))
    application.add_handler(CommandHandler("orders_waiting", orders_waiting))
    application.add_handler(CommandHandler("work_on_orders", work_on_orders))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CallbackQueryHandler(on_status_change, pattern=r"^status:\d+:.+"))
    application.add_handler(CallbackQueryHandler(on_take_order, pattern=r"^take:\d+$"))
    application.add_handler(CallbackQueryHandler(on_close_order, pattern=r"^close:\d+$"))

    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.info("Bot starting...")
    print("Startup OK: orders-bot is starting polling...")
    application = build_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()


