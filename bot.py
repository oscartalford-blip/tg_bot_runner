import requests
from bs4 import BeautifulSoup
from collections import Counter
from datetime import datetime
import json
import os

print("=== DEBUG Variables ===")
token = os.environ.get("TELEGRAM_TOKEN")
print(f"TELEGRAM_TOKEN present: {bool(token)}")
if token:
    print(f"TELEGRAM_TOKEN length: {len(token)}")
else:
    print("TELEGRAM_TOKEN is empty or missing")
key = os.environ.get("OPENWEATHER_API_KEY")
print(f"OPENWEATHER_API_KEY present: {bool(key)}")
print("=== END DEBUG ===")

import re
import threading
import time
import schedule
import telebot

# ====== ЧАСОВИЙ ПОЯС (Київ) ======
os.environ["TZ"] = "Europe/Kiev"
time.tzset()

# ====== НАЛАШТУВАННЯ ======
API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
POWER_URL = "https://www.roe.vsei.ua/disconnections"
USERS_FILE = "users.json"

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан. Добавь его в секреты.")
if not API_KEY:
    raise ValueError("OPENWEATHER_API_KEY не задан. Добавь его в секреты.")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ====== КОРИСТУВАЧІ ======
def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

def add_user(chat_id):
    users = load_users()
    if chat_id not in users:
        users.append(chat_id)
        save_users(users)

def remove_user(chat_id):
    users = load_users()
    if chat_id in users:
        users.remove(chat_id)
        save_users(users)

# ====== КЛАВІАТУРА ======
def get_main_keyboard():
    keyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(
        telebot.types.KeyboardButton("🔍 Зараз"),
        telebot.types.KeyboardButton("📊 Тиждень")
    )
    keyboard.row(
        telebot.types.KeyboardButton("⚡ Світло")
    )
    return keyboard

def get_remove_keyboard():
    return telebot.types.ReplyKeyboardRemove()

# ====== ОБРОБНИКИ КОМАНД ======
@bot.message_handler(commands=['start'])
def handle_start(message):
    add_user(message.chat.id)
    bot.send_message(
        message.chat.id,
        "✅ Ви підписались на щоденні повідомлення\n\nНатисніть кнопку нижче, щоб отримати актуальні дані прямо зараз:",
        reply_markup=get_main_keyboard()
    )

@bot.message_handler(commands=['stop'])
def handle_stop(message):
    remove_user(message.chat.id)
    bot.send_message(
        message.chat.id,
        "🔕 Ви відписались від розсилки",
        reply_markup=get_remove_keyboard()
    )

@bot.message_handler(commands=['now'])
def handle_now(message):
    bot.send_message(message.chat.id, "⏳ Збираю дані...")
    msg = build_message()
    bot.send_message(message.chat.id, msg, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "🔍 Зараз")
def handle_button_now(message):
    bot.send_message(message.chat.id, "⏳ Збираю дані...")
    msg = build_message()
    bot.send_message(message.chat.id, msg, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "📊 Тиждень")
def handle_button_week(message):
    bot.send_message(message.chat.id, "⏳ Збираю прогноз на тиждень...")
    msg = build_week_message()
    bot.send_message(message.chat.id, msg, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "⚡ Світло")
def handle_button_power(message):
    status = power_status()
    bot.send_message(
        message.chat.id,
        f"⚡ Світло (черга 6.2):\n{status}",
        reply_markup=get_main_keyboard()
    )

# ====== ПОГОДА ======
def get_daily_forecast(lat, lon):
    url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={API_KEY}&units=metric&lang=ua"
    try:
        data = requests.get(url).json()
    except:
        return ("помилка",)*3
    today = datetime.now().date()
    morning, day, evening = [], [], []
    for item in data["list"]:
        dt = datetime.fromtimestamp(item["dt"])
        if dt.date() != today:
            continue
        hour = dt.hour
        w = {
            "temp": item["main"]["temp"],
            "wind": item["wind"]["speed"],
            "humidity": item["main"]["humidity"],
            "desc": item["weather"][0]["description"]
        }
        if 6 <= hour < 12:
            morning.append(w)
        elif 12 <= hour < 18:
            day.append(w)
        elif 18 <= hour < 24:
            evening.append(w)

    def avg(block):
        if not block:
            return "немає даних"
        desc = Counter(x["desc"] for x in block).most_common(1)[0][0].capitalize()
        return (
            f"{desc} | {round(sum(x['temp'] for x in block)/len(block))}°C"
            f" | 💨 {round(sum(x['wind'] for x in block)/len(block) * 3.6)} км/год"
            f" | 💧 {round(sum(x['humidity'] for x in block)/len(block))}%"
        )
    return avg(morning), avg(day), avg(evening)

def format_forecast(name, lat, lon):
    m, d, e = get_daily_forecast(lat, lon)
    return f"""📍 {name}
🌅 Ранок: {m}
☀️ День: {d}
🌙 Вечір: {e}"""

# ====== ТИЖНЕВИЙ ПРОГНОЗ ======
DAYS_UA = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Нд"}

def get_week_forecast(lat, lon):
    url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={API_KEY}&units=metric&lang=ua"
    try:
        data = requests.get(url).json()
    except:
        return []
    today = datetime.now().date()
    days = {}
    for item in data["list"]:
        dt = datetime.fromtimestamp(item["dt"])
        d = dt.date()
        if d == today:
            continue
        if d not in days:
            days[d] = {"temps": [], "winds": [], "humid": [], "descs": []}
        days[d]["temps"].append(item["main"]["temp"])
        days[d]["winds"].append(item["wind"]["speed"])
        days[d]["humid"].append(item["main"]["humidity"])
        days[d]["descs"].append(item["weather"][0]["description"])

    result = []
    for d in sorted(days.keys())[:5]:
        info = days[d]
        t_min = round(min(info["temps"]))
        t_max = round(max(info["temps"]))
        wind = round(sum(info["winds"]) / len(info["winds"]) * 3.6)
        humid = round(sum(info["humid"]) / len(info["humid"]))
        desc = Counter(info["descs"]).most_common(1)[0][0].capitalize()
        day_name = DAYS_UA[d.weekday()]
        result.append(f"{day_name} {d.strftime('%d.%m')}  {desc} | {t_min}..{t_max}°C | 💨 {wind} км/год | 💧 {humid}%")
    return result

def build_week_message():
    lines_rivne = get_week_forecast(50.6199, 26.2516)
    lines_nova = get_week_forecast(50.619, 26.187)

    def fmt(name, lines):
        if not lines:
            return f"📍 {name}\nПомилка отримання даних"
        return f"📍 {name}\n" + "\n".join(lines)

    return f"""📅 Прогноз на 5 днів:

{fmt("Рівне", lines_rivne)}

{fmt("Нова Любомирка", lines_nova)}"""

# ====== СВІТЛО ======
def get_power_outage():
    try:
        text = BeautifulSoup(requests.get(POWER_URL).text, "html.parser").get_text("\n")
        today = datetime.now().strftime("%d.%m")
        lines = [l for l in text.split("\n") if "6.2" in l]
        for line in lines:
            if today in line:
                match = re.search(r"(\d{2}:\d{2})-(\d{2}:\d{2})", line)
                if match:
                    return match.groups()
        return None
    except:
        return None

def power_status():
    outage = get_power_outage()
    if not outage:
        return "відключень сьогодні не буде\n💡 Зараз: є світло"
    start, end = outage
    now = datetime.now().strftime("%H:%M")
    if start <= now <= end:
        status = "❌ ЗАРАЗ НЕМАЄ СВІТЛА"
    else:
        status = "✅ ЗАРАЗ Є СВІТЛО"
    return f"відключення з {start} до {end}\n{status}"

# ====== ЗБІР ПОВІДОМЛЕННЯ ======
def build_message():
    rivne = format_forecast("Рівне", 50.6199, 26.2516)
    nova = format_forecast("Нова Любомирка", 50.619, 26.187)
    power = power_status()
    return f"""
🌦️ Прогноз на сьогодні:
{rivne}
{nova}
⚡ Світло (черга 6.2):
{power}
"""

# ====== РОЗСИЛКА ======
def broadcast():
    users = load_users()
    if not users:
        return
    msg = build_message()
    for user_id in users:
        try:
            bot.send_message(user_id, msg)
        except Exception as e:
            print(f"Не вдалося надіслати {user_id}: {e}")

# ====== ПЛАНУВАЛЬНИК ======
def scheduler_loop():
    schedule.every().day.at("06:30").do(broadcast)
    while True:
        schedule.run_pending()
        time.sleep(30)

# ====== ЗАПУСК ======
if __name__ == "__main__":
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print("Бот запущено...")
    bot.infinity_polling()
