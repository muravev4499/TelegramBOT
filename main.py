import os
import logging
import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    PicklePersistence,
    ContextTypes,
    CallbackContext
)

# -------------------
# ЧИТАЄМО ТОКЕН ІЗ ЗМІННОЇ ОТОЧЕННЯ
# -------------------
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("❌ ПОМИЛКА: Змінна середовища `TOKEN` не задана або порожня!")

print(f"✅ Отриманий токен: {TOKEN[:10]}... (далі приховано)")

# -------------------
# ЗМІННІ ТА СТАНИ
# -------------------
tasks_data = {}  # { user_id: [ {id, type, datetime, city, phone, price, status, completed_date}, ... ], ... }
global_task_id_counter = 1

(
    CHOOSING_TYPE,
    CHOOSING_DATE,
    CHOOSING_TIME,
    INPUT_CITY,
    INPUT_PHONE,
    INPUT_PRICE
) = range(6)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAIN_MENU_KEYBOARD = [
    ["Додати завдання"],
    ["Перегляд завдань"],
    ["Виконані завдання"],
    ["Сума за останній місяць"],
    ["На початок"]
]

def get_main_menu():
    return ReplyKeyboardMarkup(
        MAIN_MENU_KEYBOARD,
        resize_keyboard=True
    )


# -------------------
# ХЕЛПЕРИ
# -------------------
def init_user_data_if_needed(user_id: int):
    """Ініціалізувати масив завдань, якщо ще не існує."""
    if user_id not in tasks_data:
        tasks_data[user_id] = []


def validate_phone(phone_text: str) -> bool:
    import re
    pattern = r'^(\+?\d{9,13})$'
    return bool(re.match(pattern, phone_text))


def parse_date_as_date(date_text: str) -> datetime.date:
    """
    Парсить дату з тексту у datetime.date.
    Повертає:
      - date.today() + 1 день, якщо 'завтра'
      - date.today() + 2 дні, якщо 'післязавтра'
      - або намагається розпарсити формати, як-от '15.01', '15-01', '15 01', '1501'.
    Якщо не вдасться, повертає date.today().
    """
    today = datetime.date.today()
    txt_lower = date_text.lower().strip()

    if "завтра" in txt_lower:
        return today + datetime.timedelta(days=1)
    if "післязавтра" in txt_lower:
        return today + datetime.timedelta(days=2)

    import re
    only_digits = "".join(re.findall(r'\d+', txt_lower))
    if len(only_digits) == 4:
        day = int(only_digits[:2])
        month = int(only_digits[2:])
        year = today.year  # або додати логіку вибору року
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return today
    return today


def parse_time_as_hours_minutes(time_text: str) -> (int, int):
    """
    Парсить час і повертає (години, хвилини).
    Приклади: '12:00', '12.00', '1200', '12 00', '12'.
    Якщо не вдається – повертає (9, 0) за замовчуванням.
    """
    import re
    txt = time_text.strip().lower()
    only_digits = "".join(re.findall(r'\d+', txt))

    if len(only_digits) == 4:
        h = int(only_digits[:2])
        m = int(only_digits[2:])
        return (h, m)
    elif len(only_digits) == 2:
        return (int(only_digits), 0)
    return (9, 0)


# -------------------
# /start
# -------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    init_user_data_if_needed(user_id)

    await update.message.reply_text(
        "Ласкаво просимо! Оберіть дію:",
        reply_markup=get_main_menu()
    )


# -------------------
# ДОДАТИ ЗАВДАННЯ (ConversationHandler)
# -------------------
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """КРОК 1: Вибір типу."""
    await update.message.reply_text(
        "Оберіть тип завдання або введіть свій варіант:",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["Винос"],
                ["Топозйомка"],
                ["Приватизація"],
                ["На початок"]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    return CHOOSING_TYPE


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "на початок":
        await start_command(update, context)
        return ConversationHandler.END

    context.user_data["new_task"] = {
        "type": update.message.text.strip()
    }

    await update.message.reply_text(
        "Оберіть дату (завтра / післязавтра) або введіть вручну (15.01, 15-01, 15 01 тощо):",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["Завтра"],
                ["Післязавтра"],
                ["На початок"]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    return CHOOSING_DATE


async def choose_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "на початок":
        await start_command(update, context)
        return ConversationHandler.END

    chosen_date = parse_date_as_date(update.message.text)
    context.user_data["temp_date"] = chosen_date

    # Переходимо до кроку 3 - вибір часу
    time_buttons = []
    for hour in range(9, 19):
        time_buttons.append([f"{hour}:00"])
    time_buttons.append(["На початок"])

    await update.message.reply_text(
        "Оберіть час (9:00 - 18:00) або введіть вручну (12:00, 12.00, 12 00, 12):",
        reply_markup=ReplyKeyboardMarkup(time_buttons, resize_keyboard=True, one_time_keyboard=True)
    )
    return CHOOSING_TIME


async def choose_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "на початок":
        await start_command(update, context)
        return ConversationHandler.END

    h, m = parse_time_as_hours_minutes(update.message.text)
    base_date = context.user_data.get("temp_date", datetime.date.today())
    task_dt = datetime.datetime(base_date.year, base_date.month, base_date.day, h, m)

    context.user_data["new_task"]["datetime"] = task_dt

    # КРОК 4: введення населеного пункту
    await update.message.reply_text(
        "Введіть назву населеного пункту (необов’язково). "
        "Якщо пропустити, просто натисніть Enter або кнопку 'На початок':"
    )
    return INPUT_CITY


async def input_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() == "на початок":
        await start_command(update, context)
        return ConversationHandler.END

    context.user_data["new_task"]["city"] = text if text else ""

    # КРОК 5: введення телефону
    await update.message.reply_text(
        "Введіть номер телефону замовника у форматах: +380123456789, 380123456789, 0123456789 або 123456789:"
    )
    return INPUT_PHONE


async def input_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone_text = update.message.text.strip().lower()
    if phone_text == "на початок":
        await start_command(update, context)
        return ConversationHandler.END

    if not validate_phone(phone_text):
        await update.message.reply_text(
            "Невірний формат телефону. Спробуйте ще раз або 'На початок' для відміни."
        )
        return INPUT_PHONE

    context.user_data["new_task"]["phone"] = phone_text

    # КРОК 6: вартість
    keyboard = [["Не вказувати"], ["На початок"]]
    await update.message.reply_text(
        "Введіть вартість роботи (1 - 1000000 грн). Або натисніть 'Не вказувати':",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return INPUT_PRICE


async def input_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global global_task_id_counter
    user_id = update.effective_user.id

    text = update.message.text.strip().lower()
    if text == "на початок":
        await start_command(update, context)
        return ConversationHandler.END

    if text == "не вказувати" or text == "":
        price_value = "Не вказано"
    else:
        try:
            val = int(text)
            if 1 <= val <= 1_000_000:
                price_value = val
            else:
                await update.message.reply_text(
                    "Невірне число. Спробуйте ще раз або 'На початок' для скасування."
                )
                return INPUT_PRICE
        except ValueError:
            await update.message.reply_text(
                "Не вдалося розпізнати число. Спробуйте ще раз або 'На початок'."
            )
            return INPUT_PRICE

    context.user_data["new_task"]["price"] = price_value
    context.user_data["new_task"]["status"] = "uncompleted"
    context.user_data["new_task"]["completed_date"] = None
    context.user_data["new_task"]["id"] = global_task_id_counter

    global_task_id_counter += 1
    init_user_data_if_needed(user_id)

    tasks_data[user_id].append(context.user_data["new_task"])

    # Прибираємо тимчасові дані
    del context.user_data["new_task"]
    if "temp_date" in context.user_data:
        del context.user_data["temp_date"]

    await update.message.reply_text(
        "Завдання успішно додано!",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END


# -------------------
# ПЕРЕГЛЯД ЗАВДАНЬ
# -------------------
async def view_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    init_user_data_if_needed(user_id)

    uncompleted = [t for t in tasks_data[user_id] if t["status"] == "uncompleted"]
    if not uncompleted:
        await update.message.reply_text(
            "Наразі немає невиконаних завдань.",
            reply_markup=get_main_menu()
        )
        return

    # Сортуємо за datetime
    uncompleted.sort(key=lambda x: x["datetime"])

    lines = ["<b>Список невиконаних завдань:</b>"]
    for idx, task in enumerate(uncompleted, start=1):
        dt_str = task["datetime"].strftime("%d.%m %H:%M")
        price_str = task["price"]
        lines.append(
            f"{idx}. [ID:{task['id']}] Тип: {task['type']}\n"
            f"   Дата/час: {dt_str}\n"
            f"   Місто: {task['city']} | Телефон: {task['phone']} | Ціна: {price_str}"
        )

    lines.append("\nЩо бажаєте зробити?")
    keyboard = [
        ["Видалити завдання"],
        ["Позначити завдання виконаним"],
        ["На початок"]
    ]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


# -------------------
# ВИДАЛИТИ ЗАВДАННЯ
# -------------------
async def delete_task_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Вкажіть номер завдання (у списку вище), яке бажаєте видалити.\n"
        "Або 'На початок' для відміни."
    )


async def delete_task_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    init_user_data_if_needed(user_id)

    text = update.message.text.strip().lower()
    if text == "на початок":
        await start_command(update, context)
        return

    uncompleted = [t for t in tasks_data[user_id] if t["status"] == "uncompleted"]
    uncompleted.sort(key=lambda x: x["datetime"])

    try:
        idx = int(text) - 1
        if 0 <= idx < len(uncompleted):
            to_del = uncompleted[idx]
            tasks_data[user_id].remove(to_del)
            await update.message.reply_text(
                f"Завдання [ID:{to_del['id']}] видалено.",
                reply_markup=get_main_menu()
            )
        else:
            await update.message.reply_text("Невірний номер. Спробуйте ще раз.")
    except ValueError:
        await update.message.reply_text("Будь ласка, введіть ціле число.")


# -------------------
# ПОЗНАЧИТИ ЯК ВИКОНАНЕ
# -------------------
async def complete_task_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Вкажіть номер завдання (у списку вище), яке бажаєте позначити виконаним.\n"
        "Або 'На початок' для відміни."
    )


async def complete_task_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    init_user_data_if_needed(user_id)

    text = update.message.text.strip().lower()
    if text == "на початок":
        await start_command(update, context)
        return

    uncompleted = [t for t in tasks_data[user_id] if t["status"] == "uncompleted"]
    uncompleted.sort(key=lambda x: x["datetime"])

    try:
        idx = int(text) - 1
        if 0 <= idx < len(uncompleted):
            to_complete = uncompleted[idx]
            to_complete["status"] = "completed"
            to_complete["completed_date"] = datetime.datetime.now()
            await update.message.reply_text(
                f"Завдання [ID:{to_complete['id']}] позначене виконаним.",
                reply_markup=get_main_menu()
            )
        else:
            await update.message.reply_text("Невірний номер. Спробуйте ще раз.")
    except ValueError:
        await update.message.reply_text("Будь ласка, введіть ціле число.")


# -------------------
# ВИКОНАНІ ЗАВДАННЯ
# -------------------
async def view_completed_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    init_user_data_if_needed(user_id)

    completed = [t for t in tasks_data[user_id] if t["status"] == "completed"]
    if not completed:
        await update.message.reply_text(
            "Немає виконаних завдань.",
            reply_markup=get_main_menu()
        )
        return

    completed.sort(key=lambda x: x["completed_date"], reverse=True)

    lines = ["<b>Список виконаних завдань:</b>"]
    for i, task in enumerate(completed, start=1):
        dt_completed = task["completed_date"].strftime("%d.%m %H:%M") if task["completed_date"] else "?"
        lines.append(
            f"{i}. [ID:{task['id']}] {task['type']} | Ціна: {task['price']}\n"
            f"   Виконано: {dt_completed}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=get_main_menu()
    )


# -------------------
# СУМА ЗА ОСТАННІ 30 ДНІВ
# -------------------
async def sum_last_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    init_user_data_if_needed(user_id)

    now = datetime.datetime.now()
    thirty_days_ago = now - datetime.timedelta(days=30)

    completed = [t for t in tasks_data[user_id] if t["status"] == "completed"]
    total = 0
    for t in completed:
        price = t["price"]
        cdt = t["completed_date"]
        if isinstance(price, int) and cdt and cdt >= thirty_days_ago:
            total += price

    await update.message.reply_text(
        f"Сума за останні 30 днів: {total} грн",
        reply_markup=get_main_menu()
    )


# -------------------
# ЩОДЕННЕ НАГАДУВАННЯ
# -------------------
async def daily_reminder(context: CallbackContext):
    now = datetime.datetime.now()
    today = now.date()

    for user_id, user_tasks in tasks_data.items():
        tasks_today = [
            t for t in user_tasks
            if t["status"] == "uncompleted"
            and isinstance(t["datetime"], datetime.datetime)
            and t["datetime"].date() == today
        ]

        if tasks_today:
            tasks_today.sort(key=lambda x: x["datetime"])
            lines = ["<b>Сьогоднішні завдання:</b>"]
            for task in tasks_today:
                time_str = task["datetime"].strftime("%H:%M")
                lines.append(
                    f"• [ID:{task['id']}] {task['type']} о {time_str}\n"
                    f"  (Тел: {task['phone']}, Ціна: {task['price']})"
                )

            await context.bot.send_message(
                chat_id=user_id,
                text="\n".join(lines),
                parse_mode="HTML"
            )


# -------------------
# FALLBACK
# -------------------
async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if text == "на початок":
        await start_command(update, context)
    else:
        await update.message.reply_text(
            "Вибачте, я не зрозумів. Спробуйте ще раз або натисніть 'На початок'."
        )


# -------------------
# MAIN
# -------------------
def main():
    # Persistence для зберігання стану між рестартами
    persistence = PicklePersistence(filepath="bot_data.pkl")

    app = Application.builder().token(TOKEN).persistence(persistence).build()

    # Щоденне нагадування о 6:00
    app.job_queue.run_daily(
        daily_reminder,
        time=datetime.time(hour=6, minute=0, second=0)
    )

    # ConversationHandler для "Додати завдання"
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Додати завдання$"), add_task_start)],
        states={
            CHOOSING_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_type)],
            CHOOSING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_date)],
            CHOOSING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_time)],
            INPUT_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_city)],
            INPUT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_phone)],
            INPUT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_price)],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^На початок$"), start_command)
        ]
    )

    # /start
    app.add_handler(CommandHandler("start", start_command))
    # Додати завдання
    app.add_handler(conv_handler)

    # Перегляд завдань
    app.add_handler(MessageHandler(filters.Regex("^Перегляд завдань$"), view_tasks))

    # Видалити завдання
    app.add_handler(MessageHandler(filters.Regex("^Видалити завдання$"), delete_task_request))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex("^(Перегляд завдань|Виконані завдання|Сума за останній місяць)$"),
        delete_task_confirm
    ), 1)

    # Позначити виконаним
    app.add_handler(MessageHandler(filters.Regex("^Позначити завдання виконаним$"), complete_task_request))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex("^(Перегляд завдань|Виконані завдання|Сума за останній місяць)$"),
        complete_task_confirm
    ), 2)

    # Виконані завдання
    app.add_handler(MessageHandler(filters.Regex("^Виконані завдання$"), view_completed_tasks))

    # Сума за останній місяць
    app.add_handler(MessageHandler(filters.Regex("^Сума за останній місяць$"), sum_last_month))

    # На початок
    app.add_handler(MessageHandler(filters.Regex("^На початок$"), start_command))

    # Fallback (для інших текстових повідомлень)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))

    # Запускаємо бота
    app.run_polling()


if __name__ == "__main__":
    main()
