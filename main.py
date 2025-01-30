# main.py

import os
import logging
import datetime
import re
import asyncio

# Якщо Railway/хостинг має проблеми з асинхронним циклом (наприклад, Replit),
# можна підключити nest_asyncio:
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

import aiosqlite
import dateparser
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    CallbackContext,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Зчитуємо токен з оточення (Railway → Settings → Variables)
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("❌ Змінна середовища TOKEN не встановлена!")

MAIN_MENU_KEYBOARD = [
    ["Додати завдання"],
    ["Перегляд завдань"],
    ["Виконані завдання"],
    ["Сума за останній місяць"],
    ["На початок"],
]

# =========================
# БАЗА ДАНИХ
# =========================

class TaskManager:
    def __init__(self, db_name="tasks.db"):
        self.db_name = db_name

    async def init_db(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                datetime TEXT,
                city TEXT,
                phone TEXT,
                price REAL,
                name TEXT,
                status TEXT,
                completed_date TEXT
            )''')
            await db.commit()

    async def save_task(self, user_id: int, task: dict):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                INSERT INTO tasks 
                VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                task["type"],
                task["datetime"].isoformat(),
                task["city"],
                task["phone"],
                task["price"],
                task["name"],
                "uncompleted",
                None,
            ))
            await db.commit()

    async def get_tasks(self, user_id: int, status: str = None):
        async with aiosqlite.connect(self.db_name) as db:
            query = 'SELECT * FROM tasks WHERE user_id = ?'
            if status:
                query += f' AND status = "{status}"'
            cursor = await db.execute(query, (user_id,))
            return await cursor.fetchall()

    async def delete_task(self, task_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
            await db.commit()

    async def complete_task(self, task_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                UPDATE tasks 
                SET status = ?, completed_date = ?
                WHERE id = ?
            ''', (
                "completed",
                datetime.datetime.now().isoformat(),
                task_id
            ))
            await db.commit()

    async def get_all_users(self):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT DISTINCT user_id FROM tasks')
            return await cursor.fetchall()

# Ініціалізуємо TaskManager
task_manager = TaskManager()

# =========================
# ДОПОМІЖНІ ФУНКЦІЇ
# =========================

def get_main_menu():
    """Створює клавіатуру з основним меню."""
    return ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)

def extract_data(text: str) -> dict:
    """Автоматичний парсер даних із вільного тексту."""
    patterns = {
        "date": r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|завтра|післязавтра)\b",
        "time": r"\b(\d{1,2}:\d{2})\b",
        "phone": r"(\+?38)?0\d{9}\b",
        "price": r"\b(\d+([.,]\d+)?)\s*?(грн|₴|uah)?\b",
        "city": r"(?i)(м\.|місто|смт|село)\s+([А-ЯЇІЄҐґа-яїієґʼ\s-]+)",
        "name": r"(ім['’я]я|замовник):?\s*([А-ЯЇІЄҐґ][а-яїієґʼ]+(?:\s[А-ЯЇІЄҐґ][а-яїієґʼ]+)*)",
        "type": r"(?i)\b(винос|топозйомка|приватизація)\b",
    }

    result = {}
    text_lower = text.lower()

    # Тип завдання
    type_match = re.search(patterns["type"], text_lower)
    if type_match:
        result["type"] = type_match.group(1).capitalize()
    else:
        # Спробуємо підставити відомі ключові слова
        keywords = {
            "винос": ["вивіз", "сміття", "меблі", "побутова техніка", "вантаж"],
            "топозйомка": ["топосъемка", "геодезія", "план місцевості", "розмітка", "кадастр"],
            "приватизація": ["приватизація", "документи", "земля", "квартира", "будинок", "реєстрація"]
        }
        for task_type, words in keywords.items():
            if any(word in text_lower for word in words):
                result["type"] = task_type.capitalize()
                break
        else:
            result["type"] = "Інше"

    # Дата/час (через dateparser)
    parsed_datetime = dateparser.parse(
        text, 
        languages=['uk'], 
        settings={'PREFER_DATES_FROM': 'future'}
    )
    if parsed_datetime:
        result["datetime"] = parsed_datetime
    else:
        result["datetime"] = datetime.datetime.now()

    # Телефон
    phone_match = re.search(patterns["phone"], text)
    if phone_match:
        result["phone"] = phone_match.group(0).replace(" ", "")

    # Ціна
    price_match = re.search(patterns["price"], text, re.IGNORECASE)
    if price_match:
        result["price"] = float(price_match.group(1).replace(",", "."))

    # Місто
    city_match = re.search(patterns["city"], text, re.IGNORECASE)
    if city_match:
        result["city"] = city_match.group(2).strip()

    # Ім'я
    name_match = re.search(patterns["name"], text, re.IGNORECASE)
    if name_match:
        result["name"] = name_match.group(2).strip()

    return result

# =========================
# ОСНОВНА ЛОГІКА БОТА
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start – виводить головне меню."""
    await update.message.reply_text("🏠 Головне меню:", reply_markup=get_main_menu())

async def handle_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обробка будь-якого вільного тексту (крім команд/спеціальних клавіатурних кнопок).
    Автоматично розпізнає тип завдання, дату, час, телефон тощо.
    """
    user_text = update.message.text
    parsed_data = extract_data(user_text)
    
    if not parsed_data.get("type") or not parsed_data.get("datetime"):
        await update.message.reply_text(
            "🔍 Не вдалося розпізнати дані. Приклад:\n"
            "▶ 'Вивіз меблів 25.12 о 14:00, м. Київ, 0991234567, Ім'я: Петро, 1500 грн'"
        )
        return

    try:
        task_data = {
            "type": parsed_data["type"],
            "datetime": parsed_data["datetime"],
            "city": parsed_data.get("city", "Не вказано"),
            "phone": parsed_data.get("phone", "Без телефону"),
            "price": parsed_data.get("price", 0),
            "name": parsed_data.get("name", "Без імені"),
        }
        
        # Зберігаємо в БД
        await task_manager.save_task(update.effective_user.id, task_data)
        
        response = (
            "✅ Завдання автоматично додано!\n" +
            "\n".join(f"• {k}: {v}" for k, v in parsed_data.items() if v)
        )
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Помилка: {e}")
        await update.message.reply_text("❌ Сталася помилка. Спробуйте ще раз.")

async def view_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показати усі активні (uncompleted) завдання для поточного користувача."""
    user_id = update.effective_user.id
    tasks = await task_manager.get_tasks(user_id, "uncompleted")
    
    if not tasks:
        await update.message.reply_text("📭 Немає активних завдань!")
        return

    # Створюємо Inline-кнопки для кожного завдання
    keyboard = [
        [
            InlineKeyboardButton(f"❌ Видалити {task[0]}", callback_data=f"delete_{task[0]}"),
            InlineKeyboardButton(f"✅ Виконано {task[0]}", callback_data=f"complete_{task[0]}"),
        ]
        for task in tasks
    ]
    
    await update.message.reply_text(
        "📋 Активні завдання:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка натискань на inline-кнопки (видалити/виконати)."""
    query = update.callback_query
    data = query.data

    if data.startswith("delete_"):
        task_id = int(data.split("_")[1])
        await task_manager.delete_task(task_id)
        await query.answer(f"Завдання {task_id} видалено!")
    elif data.startswith("complete_"):
        task_id = int(data.split("_")[1])
        await task_manager.complete_task(task_id)
        await query.answer(f"Завдання {task_id} виконано!")

    # Видаляємо повідомлення з кнопками після дії
    await query.message.delete()

async def view_completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показати виконані завдання (status = 'completed')."""
    user_id = update.effective_user.id
    tasks = await task_manager.get_tasks(user_id, "completed")
    
    if not tasks:
        await update.message.reply_text("📭 Немає виконаних завдань!")
        return

    text = "\n".join(
        f"✅ [ID:{task[0]}] {task[2]} - {datetime.datetime.fromisoformat(task[9]).strftime('%d.%m.%Y %H:%M')}"
        for task in tasks
    )
    await update.message.reply_text(f"📋 Виконані завдання:\n{text}")

async def daily_reminder(context: CallbackContext):
    """
    Щоденне нагадування: бот перевіряє, чи є в користувачів незавершені завдання,
    і надсилає їм повідомлення.
    """
    users = await task_manager.get_all_users()
    for user in users:
        user_id = user[0]
        tasks = await task_manager.get_tasks(user_id, "uncompleted")
        if tasks:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏰ Нагадування! У вас {len(tasks)} активних завдань."
            )

# =========================
# ГОЛОВНА АСИНХРОННА ФУНКЦІЯ
# =========================

async def main():
    # 1. Ініціалізуємо базу даних
    await task_manager.init_db()

    # 2. Створюємо Application (Telegram Bot)
    app = Application.builder().token(TOKEN).build()

    # 3. Додаємо хендлери команд і повідомлень
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(
        filters.Text(["Перегляд завдань"]), 
        view_tasks
    ))
    app.add_handler(MessageHandler(
        filters.Text(["Виконані завдання"]), 
        view_completed
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Text(["Додати завдання"]),
        handle_free_text
    ))
    app.add_handler(CallbackQueryHandler(button_handler))

    # 4. Додаємо щоденний джоб (нагадування о 9:00)
    app.job_queue.run_daily(daily_reminder, time=datetime.time(hour=9))

    # 5. Запускаємо в режимі "polling"
    await app.run_polling()

# =========================
# ТОЧКА ВХОДУ
# =========================

if __name__ == "__main__":
    # Запускаємо головну корутину через asyncio
    asyncio.run(main())
