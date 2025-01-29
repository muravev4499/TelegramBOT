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

# =========================
# НАЛАШТУВАННЯ ТА ГЛОБАЛЬНІ ЗМІННІ
# =========================

# Читаємо токен із змінної оточення (Railway, Heroku та ін.):
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("❌ ПОМИЛКА: Змінна середовища `TOKEN` не задана або порожня!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Зберігаємо завдання в пам'яті (для справжньої реалізації краще підключити БД)
tasks_data = {}  # {user_id: [ {id, type, datetime, city, phone, price, status, completed_date}, ... ]}
global_task_id_counter = 1

# СТАНИ (для ConversationHandler - «Додати завдання»)
(
    CHOOSING_TYPE,
    CHOOSING_DATE,
    CHOOSING_TIME,
    INPUT_CITY,
    INPUT_PHONE,
    INPUT_PRICE
) = range(6)

# ГОЛОВНЕ МЕНЮ
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
    """Ініціалізувати список завдань, якщо ще не існує."""
    if user_id not in tasks_data:
        tasks_data[user_id] = []

def validate_phone(phone_text: str) -> bool:
    """Перевірка коректності телефону."""
    import re
    pattern = r'^(\+?\d{9,13})$'
    return bool(re.match(pattern, phone_text))

def parse_date_as_date(date_text: str) -> datetime.date:
    """
    Парсить дату у формат datetime.date.
    - 'завтра' → today + 1 день
    - 'післязавтра' → today + 2 дні
    - спроба прочитати з 15.01, 15-01, 1501 тощо
    Якщо не вдається, повертає сьогодні.
    """
    today = datetime.date.today()
    txt = date_text.lower().strip()

    if "завтра" in txt:
        return today + datetime.timedelta(days=1)
    if "післязавтра" in txt:
        return today + datetime.timedelta(days=2)

    import re
    only_digits = "".join(re.findall(r'\d+', txt))
    if len(only_digits) == 4:
        day = int(only_digits[:2])
        month = int(only_digits[2:])
        year = today.year
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return today
    return today

def parse_time_as_hours_minutes(time_text: str) -> (int, int):
    """
    Парсить час і повертає (година, хвилина).
    Наприклад, "12:00", "1200", "12.00", "12" тощо.
    Якщо не виходить — повертає (9, 0) за замовчуванням (9:00).
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


# =========================
# 1) ДОДАТИ ЗАВДАННЯ (ConversationHandler)
# =========================

# --- КРОК 1: ВИБІР ТИПУ ---
async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

    # Зберігаємо вибраний тип
    context.user_data["new_task"] = {
        "type": update.message.text.strip()
    }

    # Переходимо до КРОКУ 2
    await update.message.reply_text(
        "Оберіть дату (завтра / післязавтра) або введіть вручну (15.01, 15-01 тощо):",
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

# --- КРОК 2: ВИБІР ДАТИ ---
async def choose_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "на початок":
        await start_command(update, context)
        return ConversationHandler.END

    chosen_date = parse_date_as_date(update.message.text)
    context.user_data["temp_date"] = chosen_date

    # Переходимо до КРОКУ 3
    time_buttons = []
    for hour in range(9, 19):
        time_buttons.append([f"{hour}:00"])
    time_buttons.append(["На початок"])

    await update.message.reply_text(
        "Оберіть час (9:00 - 18:00) або введіть вручну (12:00, 12.00, 12 00, 12):",
        reply_markup=ReplyKeyboardMarkup(time_buttons, resize_keyboard=True, one_time_keyboard=True)
    )
    return CHOOSING_TIME

# --- КРОК 3: ВИБІР ЧАСУ ---
async def choose_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text == "на початок":
        await start_command(update, context)
        return ConversationHandler.END

    h, m = parse_time_as_hours_minutes(update.message.text)
    base_date = context.user_data.get("temp_date", datetime.date.today())
    task_dt = datetime.datetime(base_date.year, base_date.month, base_date.day, h, m)

    context.user_data["new_task"]["datetime"] = task_dt

    # КРОК 4: населений пункт
    await update.message.reply_text(
        "Введіть назву населеного пункту (необов’язково). "
        "Якщо пропустити — просто натисніть Enter або кнопку 'На початок'."
    )
    return INPUT_CITY

# --- КРОК 4: ВВЕДЕННЯ МІСТА ---
async def input_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() == "на початок":
        await start_command(update, context)
        return ConversationHandler.END

    context.user_data["new_task"]["city"] = text if text else ""

    # КРОК 5: телефон
    await update.message.reply_text(
        "Введіть номер телефону замовника ( +380..., 380..., 0123..., 1234... ):"
    )
    return INPUT_PHONE

# --- КРОК 5: ВВЕДЕННЯ ТЕЛЕФОНУ ---
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
        "Введіть вартість (1 - 1000000 грн) або натисніть 'Не вказувати':",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return INPUT_PRICE

# --- КРОК 6: ВВЕДЕННЯ ВАРТОСТІ ---
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


# =========================
# 2) ПЕРЕГЛЯД ЗАВДАНЬ
# =========================
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

    # Відсортуємо за датою/часом
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


# =========================
# 3) ВИДАЛИТИ ЗАВДАННЯ
# =========================
async def delete_task_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запитуємо номер завдання для видалення.
    """
    await update.message.reply_text(
        "Вкажіть номер завдання (у списку вище), яке бажаєте видалити.\n"
        "Або 'На початок' для виходу."
    )

async def delete_task_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Видаляємо завдання з невиконаних.
    """
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


# =========================
# 4) ПОЗНАЧИТИ ЗАВДАННЯ ВИКОНАНИМ
# =========================
async def complete_task_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Запитуємо номер завдання для позначення виконаним.
    """
    await update.message.reply_text(
        "Вкажіть номер завдання (у списку вище), яке бажаєте позначити виконаним.\n"
        "Або 'На початок' для виходу."
    )

async def complete_task_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Змінюємо статус завдання на 'completed' і ставимо дату виконання.
    """
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


# =========================
# 5) ВИКОНАНІ ЗАВДАННЯ
# =========================
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


# =========================
# 6) СУМА ЗА ОСТАННІ 30 ДНІВ
# =========================
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


# =========================
# 7) ЩОДЕННЕ НАГАДУВАННЯ (опціонально)
# =========================
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


# =========================
# FALLBACK / НЕВІДПОВІДНІ ПОВІДОМЛЕННЯ
# =========================
async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if text == "на початок":
        await start_command(update, context)
    else:
        await update.message.reply_text(
            "Вибачте, я не зрозумів. Спробуйте ще раз або натисніть 'На початок'."
        )


# =========================
# MAIN
# =========================
def main():
    # Збереження стану між рестартами
    persistence = PicklePersistence(filepath="bot_data.pkl")

    # Створюємо Application
    app = Application.builder().token(TOKEN).persistence(persistence).build()

    # (Опційно) Щоденне нагадування о 6:00
    # Встановіть "python-telegram-bot[job-queue]" у requirements.txt
    app.job_queue.run_daily(daily_reminder, time=datetime.time(hour=6, minute=0, second=0))

    # --- 1) Обробник команди /start
    app.add_handler(CommandHandler("start", start_command))

    # --- 2) Додати завдання (ConversationHandler)
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
    app.add_handler(conv_handler)

    # --- 3) Перегляд завдань
    app.add_handler(MessageHandler(filters.Regex("^Перегляд завдань$"), view_tasks))

    # --- 4) Видалення завдань
    #   4.1) Натиснули "Видалити завдання"
    app.add_handler(MessageHandler(filters.Regex("^Видалити завдання$"), delete_task_request))
    #   4.2) Підтвердження видалення (введення номера)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex("^(Перегляд завдань|Виконані завдання|Сума за останній місяць)$"),
        delete_task_confirm
    ), 1)

    # --- 5) Позначити виконаним
    #   5.1) Натиснули "Позначити завдання виконаним"
    app.add_handler(MessageHandler(filters.Regex("^Позначити завдання виконаним$"), complete_task_request))
    #   5.2) Підтвердження (введення номера)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex("^(Перегляд завдань|Виконані завдання|Сума за останній місяць)$"),
        complete_task_confirm
    ), 2)

    # --- 6) Виконані завдання
    app.add_handler(MessageHandler(filters.Regex("^Виконані завдання$"), view_completed_tasks))

    # --- 7) Сума за останній місяць
    app.add_handler(MessageHandler(filters.Regex("^Сума за останній місяць$"), sum_last_month))

    # --- 8) На початок
    app.add_handler(MessageHandler(filters.Regex("^На початок$"), start_command))

    # --- 9) Fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))

    # Запуск бота
    app.run_polling()


if __name__ == "__main__":
    main()
