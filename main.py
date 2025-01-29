from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import re
from datetime import datetime, timedelta
import calendar
import os

# Список завдань
tasks = []
completed_tasks = []

def parse_date_and_time(text):
    """Парсинг дати і часу із тексту з підтримкою різних форматів."""
    now = datetime.now()
    date = ""
    time = ""

    # Пошук дати в різних форматах
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{2}/\d{2}/\d{4})\b", text)
    if date_match:
        date = date_match.group(1)
    else:
        day_names = {
            "сьогодні": 0, "завтра": 1, "понеділок": 0, "вівторок": 1, "середа": 2, "четвер": 3, "п'ятниця": 4, "субота": 5, "неділя": 6
        }
        for day_name, offset in day_names.items():
            if day_name in text.lower():
                if day_name in ["сьогодні", "завтра"]:
                    date = (now + timedelta(days=offset)).strftime("%Y-%m-%d")
                else:
                    current_weekday = now.weekday()
                    target_weekday = offset
                    days_ahead = (target_weekday - current_weekday + 7) % 7
                    if days_ahead == 0:
                        days_ahead = 7
                    date = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
                break

    # Пошук часу в різних форматах
    time_match = re.search(r"\b(\d{1,2}:\d{2}|\d{1,2}\.\d{2}|\d{1,2}\s?(AM|PM|am|pm))\b", text)
    if time_match:
        time = time_match.group(1).replace('.', ':').upper()
        # Конвертація часу формату 12 годин (AM/PM) у 24 години
        if "AM" in time or "PM" in time:
            time = datetime.strptime(time, "%I:%M %p").strftime("%H:%M")

    return date, time

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Привітання та інструкція."""
    keyboard = [["Додати завдання", "Список завдань", "Позначити виконаним", "Виконані завдання"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Привіт! Я бот для управління завданнями. Вибери дію за допомогою кнопок нижче або просто введіть текст завдання у довільному форматі.",
        reply_markup=reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка повідомлень від користувача."""
    text = update.message.text

    if text == "Додати завдання":
        await update.message.reply_text("Введіть завдання у форматі: \nТип завдання, дата, час, місце, вартість (наприклад: 'Топозйомка завтра 14:00 вул. Лісова 10 500')")

    elif text == "Список завдань":
        if not tasks:
            await update.message.reply_text("Список завдань порожній!")
        else:
            reply = "\n".join([
                f"{i + 1}. {task['type']}\nМісце: {task['place']}\nДата: {task['date']}\nЧас: {task['time']}\nВартість: {task['cost']} грн"
                for i, task in enumerate(tasks)
            ])
            await update.message.reply_text(f"Ось список завдань:\n{reply}")

    else:
        # Автоматичне зчитування завдання з тексту
        parts = text.split()
        if len(parts) >= 4:
            task_type, date_str, time_str, *location_cost = parts
            date, time = parse_date_and_time(date_str + " " + time_str)
            try:
                cost = float(location_cost[-1])
                place = " ".join(location_cost[:-1])
                new_task = {'type': task_type, 'date': date, 'time': time, 'place': place, 'cost': cost}
                tasks.append(new_task)
                await update.message.reply_text(f"✅ Завдання додано: {task_type}, {date}, {time}, {place}, {cost} грн")
            except ValueError:
                await update.message.reply_text("Помилка у форматі вартості. Введіть число.")
        else:
            await update.message.reply_text("❌ Невірний формат. Використовуйте: 'Тип завдання день час місце вартість'")

from telegram.ext import ApplicationBuilder

TOKEN = os.getenv("TOKEN")  # Railway передає токен як змінну середовища

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Бот запущено!")
app.run_polling()
