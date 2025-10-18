import asyncio
import logging
import os
from typing import Dict, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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
    get_latest_open_order_by_user,
    set_user_consent,
    has_user_consented,
    set_order_priority,
    set_order_comment,
)


# Conversation states (без города, с телефоном)
PLATFORM, FULL_NAME, DATES, MAIN_LINK, BACKUP_LINK, EXTRA_REQUEST, PROMO, PHONE = range(8)


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
SUPER_ADMIN_IDS = {
    int(cid) for cid in os.environ.get("SUPER_ADMIN_IDS", "").split(",") if cid.strip().isdigit()
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


def _user_menu_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    user_rows = [
        [KeyboardButton("Посмотреть статус заказа")],
        [KeyboardButton("Создать новый заказ")],
        [KeyboardButton("Отменить заказ")],
        [KeyboardButton("Связаться с поддержкой")],
    ]
    if is_admin:
        user_rows.append([KeyboardButton("Изменить статус заказа")])
        if update := os.environ.get("ALLOW_SUPER_MENU", "1") and True:
            user_rows.append([KeyboardButton("Поставить приоритет"), KeyboardButton("Оставить комментарий")])
    return ReplyKeyboardMarkup(user_rows, resize_keyboard=True)


def _skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Пропустить", callback_data="skip")]])


def _text_or_skip(update: Update) -> str:
    if update.message and update.message.text is not None:
        return update.message.text.strip()
    # callback on skip
    return "-"


async def _reply(update: Update, text: str, reply_markup=None) -> None:
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(text, reply_markup=reply_markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logging.info("/start from user_id=%s chat_id=%s",
                 getattr(update.effective_user, "id", None),
                 getattr(update.effective_chat, "id", None))
    print(f"/start received: user_id={getattr(update.effective_user, 'id', None)}")
    user_id = update.effective_user.id
    if has_user_consented(user_id):
        # Пропускаем согласие
        await (update.message or update.callback_query.message).reply_text(
            "Выберите тип заказа:", reply_markup=_platform_keyboard()
        )
        context.user_data["order"] = {}
        return PLATFORM
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
    # Запоминаем согласие
    if update.effective_user:
        set_user_consent(update.effective_user.id, True)
    await query.edit_message_text("Выберите тип заказа:", reply_markup=_platform_keyboard())
    context.user_data["order"] = {}
    return PLATFORM


async def choose_platform(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, key = query.data.split(":", 1)
    context.user_data.setdefault("order", {})
    context.user_data["order"]["platform"] = key
    await query.edit_message_text("Укажите Имя и Фамилию гостя на английском:", reply_markup=_skip_keyboard())
    return FULL_NAME


async def got_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _text_or_skip(update)
    context.user_data["order"]["full_name_en"] = "" if text == "-" else text
    await _reply(update, "Укажите даты:", reply_markup=_skip_keyboard())
    return DATES


async def ask_main_link_from_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _text_or_skip(update)
    context.user_data["order"]["dates"] = "" if text == "-" else text
    await _reply(update, "Ссылка на основной объект:", reply_markup=_skip_keyboard())
    return MAIN_LINK


async def ask_backup_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _text_or_skip(update)
    context.user_data["order"]["main_link"] = "" if text == "-" else text
    await _reply(update, "Ссылка на запасной объект:", reply_markup=_skip_keyboard())
    return BACKUP_LINK


async def ask_extra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _text_or_skip(update)
    context.user_data["order"]["backup_link"] = "" if text == "-" else text
    await _reply(update, "Дополнительный запрос:", reply_markup=_skip_keyboard())
    return EXTRA_REQUEST


async def ask_promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _text_or_skip(update)
    context.user_data["order"]["extra_request"] = "" if text == "-" else text
    await _reply(update, "Промокод:", reply_markup=_skip_keyboard())
    return PROMO


async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _text_or_skip(update)
    context.user_data["order"]["promo_code"] = "" if text == "-" else text
    await _reply(update, "Укажите номер телефона:", reply_markup=_skip_keyboard())
    return PHONE


async def finalize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = _text_or_skip(update)
    context.user_data["order"]["phone"] = "" if text == "-" else text

    order: Dict[str, str] = context.user_data["order"]
    order["user_id"] = update.effective_user.id
    order["status"] = "В работе"
    order_id = insert_order(order)

    summary = (
        f"Заказ №{order_id} сохранен.\n\n"
        f"Платформа: {order['platform']}\n"
        f"Имя (EN): {order.get('full_name_en','')}\n"
        f"Даты: {order['dates']}\n"
        f"Основной объект: {order.get('main_link','')}\n"
        f"Запасной объект: {order.get('backup_link','')}\n"
        f"Доп. запрос: {order.get('extra_request','')}\n"
        f"Промокод: {order.get('promo_code','')}\n"
        f"Телефон: {order.get('phone','')}\n"
        f"Статус: В работе"
    )
    await update.message.reply_text(summary)
    await update.message.reply_text("Спасибо! Ваш заказ принят в работу.")

    # Показать меню пользователю сразу после создания заказа
    is_admin_user = update.effective_user.id in ADMIN_CHAT_IDS
    await update.message.reply_text("Меню:", reply_markup=_user_menu_keyboard(is_admin_user))

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


async def show_user_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_admin = update.effective_user.id in ADMIN_CHAT_IDS
    await (update.message or update.callback_query.message).reply_text(
        "Меню:", reply_markup=_user_menu_keyboard(is_admin)
    )


async def handle_menu_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    is_admin = update.effective_user.id in ADMIN_CHAT_IDS
    if text == "Посмотреть статус заказа":
        row = get_latest_open_order_by_user(update.effective_user.id)
        if not row:
            await update.message.reply_text("У вас нет активных заказов.")
        else:
            await update.message.reply_text(
                f"№{row['id']} | Статус: {row['status']}\nПлатформа: {row['platform']}\nГород: {row['city']}\nДаты: {row['dates']}",
                reply_markup=_user_menu_keyboard(is_admin),
            )
        return
    if text == "Создать новый заказ":
        await update.message.reply_text("Запускаю оформление…", reply_markup=ReplyKeyboardRemove())
        # перезапускаем диалог
        return await start(update, context)
    if text == "Отменить заказ":
        row = get_latest_open_order_by_user(update.effective_user.id)
        if not row:
            await update.message.reply_text("Активных заказов нет.", reply_markup=_user_menu_keyboard(is_admin))
        else:
            update_order_status(int(row['id']), "Отменен")
            await update.message.reply_text("Заказ отменен.", reply_markup=_user_menu_keyboard(is_admin))
        return
    if text == "Связаться с поддержкой":
        await update.message.reply_text("Поддержка: @your_support_contact", reply_markup=_user_menu_keyboard(is_admin))
        return
    if text == "Изменить статус заказа" and is_admin:
        # Показываем последний заказ пользователя (для простоты) с кнопками статусов
        row = get_latest_open_order_by_user(update.effective_user.id)
        if not row:
            await update.message.reply_text("Нет заказа для изменения.", reply_markup=_user_menu_keyboard(is_admin))
        else:
            await update.message.reply_text(
                f"Изменение статуса для заказа №{row['id']}", reply_markup=_status_keyboard(int(row['id']))
            )
        return
    if text == "Поставить приоритет":
        if update.effective_user.id not in SUPER_ADMIN_IDS:
            await update.message.reply_text("Недостаточно прав.")
            return
        await update.message.reply_text("Укажите: <order_id> <priority(0-5)>")
        context.user_data["awaiting_priority"] = True
        return
    if text == "Оставить комментарий":
        if update.effective_user.id not in SUPER_ADMIN_IDS:
            await update.message.reply_text("Недостаточно прав.")
            return
        await update.message.reply_text("Укажите: <order_id> <комментарий>")
        context.user_data["awaiting_comment"] = True
        return

    # Super admin inputs
    if context.user_data.get("awaiting_priority"):
        try:
            oid_str, prio_str = text.split(maxsplit=1)
            set_order_priority(int(oid_str), max(0, min(5, int(prio_str))))
            await update.message.reply_text("Приоритет обновлен.")
        except Exception:
            await update.message.reply_text("Формат: <order_id> <priority(0-5)>")
        finally:
            context.user_data.pop("awaiting_priority", None)
        return
    if context.user_data.get("awaiting_comment"):
        try:
            oid_str, comment = text.split(maxsplit=1)
            set_order_comment(int(oid_str), comment)
            await update.message.reply_text("Комментарий сохранен.")
        except Exception:
            await update.message.reply_text("Формат: <order_id> <комментарий>")
        finally:
            context.user_data.pop("awaiting_comment", None)
        return


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
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_full_name), CallbackQueryHandler(got_full_name, pattern="^skip$")],
            DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_main_link_from_dates), CallbackQueryHandler(ask_main_link_from_dates, pattern="^skip$")],
            MAIN_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_backup_link), CallbackQueryHandler(ask_backup_link, pattern="^skip$")],
            BACKUP_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_extra), CallbackQueryHandler(ask_extra, pattern="^skip$")],
            EXTRA_REQUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_promo), CallbackQueryHandler(ask_promo, pattern="^skip$")],
            PROMO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone), CallbackQueryHandler(ask_phone, pattern="^skip$")],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize), CallbackQueryHandler(finalize, pattern="^skip$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv)
    application.add_handler(CommandHandler("orders", list_orders))
    application.add_handler(CommandHandler("orders_waiting", orders_waiting))
    application.add_handler(CommandHandler("work_on_orders", work_on_orders))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("menu", show_user_menu))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_click))
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


