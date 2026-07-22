"""
БОТ ДЛЯ ОБМЕНА ВИДЕО
С РЕЙТИНГОМ, КАТЕГОРИЯМИ И VIP
"""

import os
import sqlite3
import hashlib
import asyncio
import aiohttp
import uuid
import logging
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

# ==================================================
# КОНФИГУРАЦИЯ
# ==================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8696076422:AAHumHjSmQd24T4P94Nmad1iLJdrLwfLbIk")
ADMIN_ID = 8559381302

# Цены
VIP_PRICE = 299
TRIAL_PRICE = 39
DAILY_LIMIT = 30
MIN_RATING_TO_SHOW = 0
AUTO_DELETE_RATING = -10
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 ГБ

# RollyPay
ROLLYPAY_API_KEY = "z39_r_COJdiB7PWeddOYvzT2rx4cjIbS1m4JJcgBTi0"
ROLLYPAY_CALLBACK_URL = "https://bot-obmen-sw4i.onrender.com/webhook"

# Категории
CATEGORIES = {
    "celebrity": {"name": "⭐ Знаменитости", "emoji": "⭐"},
    "alt": {"name": "🎭 Альтушки", "emoji": "🎭"},
    "schoolgirls": {"name": "👧 Школьницы", "emoji": "👧"},
    "extreme": {"name": "🔥 Жесть", "emoji": "🔥"},
    "hidden_cam": {"name": "📸 Скрытые камеры", "emoji": "📸"},
    "parties": {"name": "🍻 Вписки", "emoji": "🍻"},
    "zoo": {"name": "🐕 Зоо", "emoji": "🐕"},
    "gay": {"name": "🌈 Гей", "emoji": "🌈"},
    "stashers": {"name": "💀 Закладчицы", "emoji": "💀"},
    "rapes": {"name": "💀 Износы", "emoji": "💀"},
    "other": {"name": "📁 Без категории", "emoji": "📁"}
}

# ==================================================
# FLASK
# ==================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "🤖 Бот работает!"

@flask_app.route('/health')
def health():
    return "OK", 200

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    data = await request.get_json()
    if not data:
        return jsonify({"status": "error"}), 400
    status = data.get('status')
    if status == 'paid':
        order_id = data.get('order_id')
        parts = order_id.split('_')
        user_id = int(parts[1])
        duration = parts[2] if len(parts) > 2 else 'month'
        if duration == 'trial':
            activate_trial(user_id)
        else:
            activate_vip(user_id, months=1)
        logging.info(f"✅ VIP активирован для {user_id}")
        return jsonify({"status": "ok"}), 200
    return jsonify({"status": "error"}), 400

# ==================================================
# БАЗА ДАННЫХ
# ==================================================
DB_PATH = "bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            vip_status INTEGER DEFAULT 0,
            vip_until TEXT,
            vip_duration TEXT,
            daily_exchanges INTEGER DEFAULT 0,
            last_exchange_date TEXT,
            trial_used INTEGER DEFAULT 0,
            total_sent INTEGER DEFAULT 0,
            total_received INTEGER DEFAULT 0,
            selected_category TEXT,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT UNIQUE,
            file_unique_id TEXT UNIQUE,
            file_hash TEXT,
            file_size INTEGER,
            uploaded_by INTEGER,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            mime_type TEXT,
            duration INTEGER,
            width INTEGER,
            height INTEGER,
            likes INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0,
            rating INTEGER DEFAULT 0,
            checked INTEGER DEFAULT 0,
            category TEXT,
            views INTEGER DEFAULT 0,
            last_sent_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS video_votes (
            user_id INTEGER,
            video_id INTEGER,
            vote TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, video_id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            user_id INTEGER,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ База данных готова!")

# ==================================================
# ФУНКЦИИ
# ==================================================

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result

def create_user(user_id, first_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)', (user_id, first_name))
    conn.commit()
    conn.close()

def is_vip(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT vip_status, vip_until FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    if not result:
        return False
    vip_status, vip_until = result
    if vip_status == 1 and vip_until:
        try:
            if datetime.fromisoformat(vip_until) > datetime.now():
                return True
        except:
            pass
    return False

def get_vip_info(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT vip_status, vip_until, vip_duration FROM users WHERE user_id = ?', (user_id,))
    return c.fetchone()

def activate_vip(user_id, months=1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    vip_until = (datetime.now() + timedelta(days=30 * months)).isoformat()
    c.execute('UPDATE users SET vip_status = 1, vip_until = ?, vip_duration = ? WHERE user_id = ?', 
              (vip_until, f"{months} месяц(ев)", user_id))
    conn.commit()
    conn.close()
    return True

def activate_trial(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT trial_used FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    if result and result[0] == 1:
        conn.close()
        return False
    vip_until = (datetime.now() + timedelta(days=3)).isoformat()
    c.execute('UPDATE users SET vip_status = 1, vip_until = ?, vip_duration = "3 дня (пробный)", trial_used = 1 WHERE user_id = ?', 
              (vip_until, user_id))
    conn.commit()
    conn.close()
    return True

def get_vip_count():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users WHERE vip_status = 1')
    return c.fetchone()[0] or 0

def get_vip_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT user_id, first_name, vip_until, vip_duration FROM users WHERE vip_status = 1')
    return c.fetchall()

def get_daily_exchanges(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().date().isoformat()
    c.execute('SELECT daily_exchanges FROM users WHERE user_id = ? AND last_exchange_date = ?', (user_id, today))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def increment_daily_exchanges(user_id, count=1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().date().isoformat()
    c.execute('UPDATE users SET daily_exchanges = daily_exchanges + ?, last_exchange_date = ? WHERE user_id = ?', 
              (count, today, user_id))
    conn.commit()
    conn.close()

def add_video(file_id, file_unique_id, file_hash, file_size, uploaded_by, mime_type, duration, width, height):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''
            INSERT INTO videos (file_id, file_unique_id, file_hash, file_size, uploaded_by, mime_type, duration, width, height)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (file_id, file_unique_id, file_hash, file_size, uploaded_by, mime_type, duration, width, height))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def get_video_by_hash(file_hash):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT file_id FROM videos WHERE file_hash = ? AND is_active = 1', (file_hash,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_video_rating(video_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT likes, dislikes, rating FROM videos WHERE id = ?', (video_id,))
    result = c.fetchone()
    conn.close()
    return result if result else (0, 0, 0)

def update_rating(video_id, action):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if action == 'like':
        c.execute('UPDATE videos SET likes = likes + 1, rating = rating + 1 WHERE id = ?', (video_id,))
    elif action == 'dislike':
        c.execute('UPDATE videos SET dislikes = dislikes + 1, rating = rating - 1 WHERE id = ?', (video_id,))
    conn.commit()
    conn.close()

def delete_video(video_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE videos SET is_active = 0 WHERE id = ?', (video_id,))
    conn.commit()
    conn.close()

def get_random_videos(count, min_rating=MIN_RATING_TO_SHOW):
    """Получает случайные видео (включая свои)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT id, file_id, rating, likes, dislikes 
        FROM videos WHERE is_active = 1 AND rating >= ?
        ORDER BY RANDOM() LIMIT ?
    ''', (min_rating, count))
    result = c.fetchall()
    conn.close()
    return result

def get_video_count():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM videos WHERE is_active = 1')
    return c.fetchone()[0] or 0

def get_user_video_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM videos WHERE uploaded_by = ? AND is_active = 1', (user_id,))
    return c.fetchone()[0] or 0

def user_has_voted(user_id, video_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT 1 FROM video_votes WHERE user_id = ? AND video_id = ?', (user_id, video_id))
    result = c.fetchone()
    conn.close()
    return result is not None

def add_user_vote(user_id, video_id, vote):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO video_votes (user_id, video_id, vote) VALUES (?, ?, ?)', (user_id, video_id, vote))
    conn.commit()
    conn.close()

def add_complaint(video_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO complaints (video_id, user_id) VALUES (?, ?)', (video_id, user_id))
    conn.commit()
    conn.close()

def get_complaint_count(video_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM complaints WHERE video_id = ?', (video_id,))
    return c.fetchone()[0] or 0

def auto_cleanup():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE videos SET is_active = 0 WHERE rating < ? AND is_active = 1', (AUTO_DELETE_RATING,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted

def get_user_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    total = c.fetchone()[0] or 0
    c.execute('SELECT COUNT(*) FROM users WHERE vip_status = 1')
    vip = c.fetchone()[0] or 0
    today = datetime.now().date().isoformat()
    c.execute('SELECT COUNT(*) FROM users WHERE joined_at LIKE ?', (today + '%',))
    today_users = c.fetchone()[0] or 0
    conn.close()
    return total, vip, today_users

def get_video_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM videos WHERE is_active = 1')
    total = c.fetchone()[0] or 0
    c.execute('SELECT COUNT(*) FROM videos WHERE is_active = 1 AND rating >= 5')
    good = c.fetchone()[0] or 0
    c.execute('SELECT COUNT(*) FROM videos WHERE is_active = 1 AND rating < 5')
    bad = c.fetchone()[0] or 0
    c.execute('SELECT AVG(rating) FROM videos WHERE is_active = 1')
    avg = c.fetchone()[0] or 0
    conn.close()
    return total, good, bad, round(avg, 2)

def get_category_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    stats = {}
    for cat_key in CATEGORIES.keys():
        c.execute('SELECT COUNT(*) FROM videos WHERE is_active = 1 AND category = ?', (cat_key,))
        stats[cat_key] = c.fetchone()[0] or 0
    conn.close()
    return stats

def get_vip_expiring_soon():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    c.execute('''
        SELECT user_id, first_name, vip_until 
        FROM users WHERE vip_status = 1 AND vip_until LIKE ?
    ''', (tomorrow + '%',))
    result = c.fetchall()
    conn.close()
    return result

# ==================================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ==================================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ==================================================
# ФУНКЦИЯ ДЛЯ ПЛАТЕЖЕЙ
# ==================================================
async def create_rollypay_payment(amount: int, user_id: int, description: str, duration: str = 'month') -> str:
    url = "https://rollypay.io/api/v1/payments"
    headers = {
        "X-API-Key": ROLLYPAY_API_KEY,
        "Content-Type": "application/json",
        "X-Nonce": str(uuid.uuid4())
    }
    payload = {
        "amount": str(amount),
        "payment_currency": "RUB",
        "order_id": f"order_{user_id}_{duration}_{int(datetime.now().timestamp())}",
        "description": description,
        "callback_url": ROLLYPAY_CALLBACK_URL,
        "success_url": "https://t.me/blogprivatbot",
        "fail_url": "https://t.me/blogprivatbot",
        "merchant_fee": "true",
        "test": "true"
    }
    
    async with aiohttp.ClientSession() as client:
        async with client.post(url, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("pay_url")
            else:
                logging.error(f"Ошибка RollyPay: {response.status}")
                return None

# ==================================================
# КЛАВИАТУРЫ
# ==================================================

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обменяться", callback_data="exchange")],
        [InlineKeyboardButton(text="👑 Купить VIP", callback_data="buy_vip")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🎁 Пробный период (3 дня / 39 ₽)", callback_data="buy_trial")]
    ])

def get_vip_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 VIP на 1 месяц (299 ₽)", callback_data="pay_vip")],
        [InlineKeyboardButton(text="🎁 Пробный период (3 дня / 39 ₽)", callback_data="pay_trial")],
        [InlineKeyboardButton(text="👈 Назад", callback_data="back_to_main")]
    ])

def get_exchange_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Получить видео", callback_data="get_videos")],
        [InlineKeyboardButton(text="👈 Назад", callback_data="back_to_main")]
    ])

def get_vip_exchange_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Выбрать категорию", callback_data="vip_select_category")],
        [InlineKeyboardButton(text="🎲 Рандомная категория", callback_data="vip_random_category")],
        [InlineKeyboardButton(text="🏆 Топ видео", callback_data="vip_top")],
        [InlineKeyboardButton(text="📊 Статистика категорий", callback_data="vip_category_stats")],
        [InlineKeyboardButton(text="🔄 Сменить категорию", callback_data="vip_change_category")],
        [InlineKeyboardButton(text="👈 Назад", callback_data="back_to_main")]
    ])

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Категоризация (1 видео)", callback_data="admin_check_one")],
        [InlineKeyboardButton(text="📉 Видео с рейтингом < 5", callback_data="admin_check_low_rating")],
        [InlineKeyboardButton(text="📩 Жалобы (5+)", callback_data="admin_check_complaints")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👑 Список VIP", callback_data="admin_vip_list")],
        [InlineKeyboardButton(text="🗑 Автоочистка", callback_data="admin_cleanup")]
    ])

def get_video_rating_keyboard(video_id: int, likes: int, dislikes: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(f"👍 {likes}", callback_data=f"like_{video_id}"),
            InlineKeyboardButton(f"👎 {dislikes}", callback_data=f"dislike_{video_id}")
        ],
        [InlineKeyboardButton("📩 Жалоба", callback_data=f"complaint_{video_id}")]
    ])

def get_admin_video_keyboard(video_id: int):
    buttons = []
    for cat_key, cat_data in CATEGORIES.items():
        buttons.append(InlineKeyboardButton(
            f"{cat_data['emoji']} {cat_data['name']}",
            callback_data=f"set_cat_{video_id}_{cat_key}"
        ))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([
        InlineKeyboardButton("🔄 Сменить категорию", callback_data=f"change_cat_{video_id}"),
        InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_delete_{video_id}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_admin_low_rating_keyboard(video_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton("❤️ Восстановить (рейтинг → 0)", callback_data=f"restore_{video_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_delete_{video_id}")
        ]
    ])

# ==================================================
# 1. КОМАНДЫ
# ==================================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    create_user(user_id, first_name)
    
    vip_status = "✅ Активен" if is_vip(user_id) else "❌ Не активен"
    video_count = get_video_count()
    user_video_count = get_user_video_count(user_id)
    
    text = f"""🎬 <b>Добро пожаловать в бот для обмена видео!</b>

👤 Пользователь: {first_name}
👑 VIP статус: {vip_status}
📊 Видео в базе: {video_count}
📤 Ты отправил: {user_video_count} видео

📌 <b>Правила:</b>
• Бесплатно: до {DAILY_LIMIT} видео в день
• VIP: безлимитный обмен + выбор категории
• Пробный период: 3 дня за {TRIAL_PRICE} ₽

🔄 Отправь мне ВИДЕО, и я сохраню его!"""
    
    await message.answer(text, reply_markup=get_main_keyboard())

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Только для админа!")
        return
    
    vip_count = get_vip_count()
    video_count = get_video_count()
    
    text = f"""⚙️ <b>Админ-панель</b>

📌 <b>Статистика:</b>
• VIP пользователей: {vip_count}
• Всего видео: {video_count}"""
    
    await message.answer(text, reply_markup=get_admin_keyboard())

@dp.message(Command("export_db"))
async def export_db(message: Message):
    """Отправляет админу файл базы данных"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Только для админа!")
        return
    
    if not os.path.exists(DB_PATH):
        await message.answer("❌ Файл базы данных не найден!")
        return
    
    try:
        with open(DB_PATH, "rb") as f:
            await message.answer_document(
                document=f,
                caption=f"📁 База данных бота (bot.db)\n📊 Размер: {os.path.getsize(DB_PATH)} байт"
            )
        await message.answer("✅ База данных отправлена!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ==================================================
# 2. ВИДЕО
# ==================================================

@dp.message(F.video | F.animation)
async def handle_video(message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    create_user(user_id, first_name)
    
    if message.video:
        video = message.video
        media_type = "видео"
    else:
        video = message.animation
        media_type = "GIF"
    
    # Проверка размера
    if video.file_size > MAX_FILE_SIZE:
        await message.answer(f"❌ <b>Файл слишком большой!</b>\n\n⚠️ Максимум: 2 ГБ")
        return
    
    if video.duration and video.duration < 3:
        await message.answer("❌ <b>Слишком короткое видео!</b> (минимум 3 секунды)")
        return
    
    if video.file_size < 50 * 1024:
        await message.answer("❌ <b>Файл слишком маленький!</b> (минимум 50 КБ)")
        return
    
    # Проверка дубликата через file_unique_id
    file_hash = video.file_unique_id
    existing_file_id = get_video_by_hash(file_hash)
    
    if existing_file_id:
        await message.answer("❌ <b>Это видео уже есть в базе!</b>\n\n📌 Дубликаты не сохраняются.")
        return
    
    # Сохраняем
    success = add_video(
        file_id=video.file_id,
        file_unique_id=video.file_unique_id,
        file_hash=file_hash,
        file_size=video.file_size,
        uploaded_by=user_id,
        mime_type=video.mime_type,
        duration=video.duration,
        width=video.width,
        height=video.height
    )
    
    if success:
        video_count = get_video_count()
        user_video_count = get_user_video_count(user_id)
        await message.answer(
            f"✅ <b>{media_type.capitalize()} сохранено!</b>\n\n"
            f"📊 Всего в базе: {video_count}\n"
            f"📤 Ты отправил: {user_video_count}\n\n"
            f"🔄 Нажми «Обменяться» для получения видео!"
        )
    else:
        await message.answer("❌ Ошибка при сохранении. Попробуй ещё раз.")

# ==================================================
# 3. ОСНОВНЫЕ CALLBACK'и
# ==================================================

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    first_name = callback.from_user.first_name
    create_user(user_id, first_name)
    
    vip_status = "✅ Активен" if is_vip(user_id) else "❌ Не активен"
    video_count = get_video_count()
    user_video_count = get_user_video_count(user_id)
    
    text = f"""🎬 <b>Главное меню</b>

👤 Пользователь: {first_name}
👑 VIP статус: {vip_status}
📊 Видео в базе: {video_count}
📤 Ты отправил: {user_video_count} видео"""
    
    await callback.message.edit_text(text, reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "stats")
async def stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    vip_status = "✅ Активен" if is_vip(user_id) else "❌ Не активен"
    video_count = get_video_count()
    user_video_count = get_user_video_count(user_id)
    daily = get_daily_exchanges(user_id)
    limit = "∞" if is_vip(user_id) else str(DAILY_LIMIT)
    
    text = f"""📊 <b>Твоя статистика</b>

👑 VIP: {vip_status}
📤 Отправлено: {user_video_count}
🔄 Обменов сегодня: {daily} / {limit}
📊 Всего в базе: {video_count}"""
    
    await callback.message.edit_text(text, reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "exchange")
async def exchange(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_vip(user_id):
        daily = get_daily_exchanges(user_id)
        if daily >= DAILY_LIMIT:
            await callback.answer(f"❌ Ты исчерпал дневной лимит ({DAILY_LIMIT})!\nКупи VIP для безлимита.", show_alert=True)
            return
    
    text = """🔄 <b>Обмен видео</b>

📌 Отправь видео → оно сохранится в базу
📌 Нажми «Получить видео» → получи случайное видео

📊 Правила:
• Бесплатно: до 30 видео в день
• VIP: безлимитный обмен
• Дубликаты не сохраняются"""
    
    if is_vip(user_id):
        await callback.message.edit_text(text, reply_markup=get_vip_exchange_keyboard())
    else:
        await callback.message.edit_text(text, reply_markup=get_exchange_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "get_videos")
async def get_videos(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_vip(user_id):
        daily = get_daily_exchanges(user_id)
        if daily >= DAILY_LIMIT:
            await callback.answer("❌ Дневной лимит исчерпан!", show_alert=True)
            return
    
    user_video_count = get_user_video_count(user_id)
    if user_video_count == 0:
        await callback.answer("❌ Сначала отправь видео!", show_alert=True)
        return
    
    # Получаем до 10 видео (без исключения пользователя)
    videos = get_random_videos(10, min_rating=MIN_RATING_TO_SHOW)
    
    if not videos:
        await callback.answer("❌ В базе нет подходящих видео!", show_alert=True)
        return
    
    sent = 0
    for video_id, file_id, rating, likes, dislikes in videos:
        try:
            await bot.send_video(
                chat_id=user_id,
                video=file_id,
                reply_markup=get_video_rating_keyboard(video_id, likes, dislikes)
            )
            sent += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            logging.error(f"Ошибка отправки: {e}")
    
    # Увеличиваем счетчик на количество отправленных видео
    increment_daily_exchanges(user_id, sent)
    
    remaining = DAILY_LIMIT - get_daily_exchanges(user_id) if not is_vip(user_id) else "∞"
    
    await callback.message.answer(f"✅ Отправлено {sent} видео!\n📊 Осталось обменов: {remaining}")
    await callback.answer()

# ==================================================
# 4. VIP-ФУНКЦИИ
# ==================================================

@dp.callback_query(F.data == "buy_vip")
async def buy_vip(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if is_vip(user_id):
        vip_info = get_vip_info(user_id)
        if vip_info:
            _, vip_until, duration = vip_info
            text = f"""👑 <b>У тебя уже есть VIP!</b>

📅 До: {vip_until[:10]}
📆 Тип: {duration}

💳 <b>Продлить подписку можно ниже:</b>"""
            await callback.message.edit_text(text, reply_markup=get_vip_keyboard())
            await callback.answer()
            return
    
    text = """👑 <b>VIP подписка</b>

🔥 <b>Преимущества VIP:</b>
• ✅ Безлимитный обмен видео (без 30/день)
• ✅ Доступ ко ВСЕЙ базе видео
• ✅ Выбор категории для обмена
• ✅ Только видео с высоким рейтингом
• ✅ Приоритетная обработка запросов
• ✅ Техподдержка 24/7

💰 <b>Цены:</b>
• 1 месяц — 299 ₽
• Пробный период — 3 дня за 39 ₽"""
    
    await callback.message.edit_text(text, reply_markup=get_vip_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "pay_vip")
async def pay_vip(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if is_vip(user_id):
        await callback.answer("❌ У тебя уже есть VIP!", show_alert=True)
        return
    
    payment_url = await create_rollypay_payment(VIP_PRICE, user_id, "VIP подписка на 1 месяц", "month")
    
    if payment_url:
        text = f"""💳 <b>Оплата VIP подписки</b>

💰 Сумма: {VIP_PRICE} ₽
📅 Период: 1 месяц

✅ Нажми на кнопку ниже, чтобы оплатить."""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {VIP_PRICE} ₽", url=payment_url)],
            [InlineKeyboardButton(text="👈 Назад", callback_data="buy_vip")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard)
    else:
        await callback.answer("❌ Ошибка создания платежа. Попробуй позже.", show_alert=True)

@dp.callback_query(F.data == "pay_trial")
async def pay_trial(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT trial_used FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result and result[0] == 1:
        await callback.answer("❌ Ты уже использовал пробный период!", show_alert=True)
        return
    
    payment_url = await create_rollypay_payment(TRIAL_PRICE, user_id, "Пробный VIP на 3 дня", "trial")
    
    if payment_url:
        text = f"""💳 <b>Оплата пробного периода</b>

💰 Сумма: {TRIAL_PRICE} ₽
📅 Период: 3 дня

✅ Нажми на кнопку ниже, чтобы оплатить."""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {TRIAL_PRICE} ₽", url=payment_url)],
            [InlineKeyboardButton(text="👈 Назад", callback_data="buy_vip")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard)
    else:
        await callback.answer("❌ Ошибка создания платежа. Попробуй позже.", show_alert=True)

# ==================================================
# 5. VIP-ОБМЕН ПО КАТЕГОРИЯМ
# ==================================================

@dp.callback_query(F.data == "vip_select_category")
async def vip_select_category(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_vip(user_id):
        await callback.answer("❌ Только для VIP!", show_alert=True)
        return
    
    cat_stats = get_category_stats()
    buttons = []
    for cat_key, count in cat_stats.items():
        if count > 0 and cat_key != 'other':
            cat_data = CATEGORIES[cat_key]
            buttons.append([InlineKeyboardButton(
                text=f"{cat_data['emoji']} {cat_data['name']} ({count})",
                callback_data=f"vip_set_cat_{cat_key}"
            )])
    
    if not buttons:
        await callback.answer("❌ Нет категорий с видео!", show_alert=True)
        return
    
    buttons.append([InlineKeyboardButton(text="👈 Назад", callback_data="exchange")])
    await callback.message.edit_text(
        "🎯 <b>Выбери категорию для обмена</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("vip_set_cat_"))
async def vip_set_category(callback: CallbackQuery):
    user_id = callback.from_user.id
    category = callback.data.replace("vip_set_cat_", "")
    
    if not is_vip(user_id):
        await callback.answer("❌ Только для VIP!", show_alert=True)
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE users SET selected_category = ? WHERE user_id = ?', (category, user_id))
    conn.commit()
    conn.close()
    
    await callback.answer(f"✅ Категория '{CATEGORIES[category]['name']}' выбрана!")
    await callback.message.edit_text(
        f"✅ <b>Категория выбрана!</b>\n\n📁 {CATEGORIES[category]['emoji']} {CATEGORIES[category]['name']}",
        reply_markup=get_vip_exchange_keyboard()
    )

@dp.callback_query(F.data == "vip_random_category")
async def vip_random_category(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_vip(user_id):
        await callback.answer("❌ Только для VIP!", show_alert=True)
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT selected_category FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    
    category = result[0] if result and result[0] else None
    if not category:
        await callback.answer("❌ Сначала выбери категорию!", show_alert=True)
        return
    
    user_video_count = get_user_video_count(user_id)
    if user_video_count == 0:
        await callback.answer("❌ Сначала отправь видео!", show_alert=True)
        return
    
    count = min(user_video_count, 10)
    videos = get_random_videos(count)
    
    if not videos:
        await callback.answer(f"❌ В категории {CATEGORIES[category]['name']} нет видео!", show_alert=True)
        return
    
    sent = 0
    for video_id, file_id, rating, likes, dislikes in videos:
        try:
            await bot.send_video(
                chat_id=user_id,
                video=file_id,
                reply_markup=get_video_rating_keyboard(video_id, likes, dislikes)
            )
            sent += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            logging.error(f"Ошибка отправки: {e}")
    
    await callback.message.answer(f"✅ Отправлено {sent} видео!")
    await callback.answer()

@dp.callback_query(F.data == "vip_top")
async def vip_top(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_vip(user_id):
        await callback.answer("❌ Только для VIP!", show_alert=True)
        return
    
    videos = get_random_videos(10)
    if not videos:
        await callback.answer("❌ Нет видео с рейтингом!", show_alert=True)
        return
    
    await callback.answer("🏆 Отправляю топ-10 видео...")
    
    for video_id, file_id, rating, likes, dislikes in videos:
        try:
            await bot.send_video(
                chat_id=user_id,
                video=file_id,
                reply_markup=get_video_rating_keyboard(video_id, likes, dislikes)
            )
            await asyncio.sleep(0.3)
        except Exception as e:
            logging.error(f"Ошибка отправки: {e}")

@dp.callback_query(F.data == "vip_category_stats")
async def vip_category_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_vip(user_id):
        await callback.answer("❌ Только для VIP!", show_alert=True)
        return
    
    cat_stats = get_category_stats()
    text = "📊 <b>Статистика по категориям</b>\n\n"
    for cat_key, count in cat_stats.items():
        if count > 0:
            cat_data = CATEGORIES[cat_key]
            text += f"{cat_data['emoji']} {cat_data['name']}: {count} видео\n"
    
    text += f"\n📊 Всего видео: {get_video_count()}"
    
    await callback.message.edit_text(text, reply_markup=get_vip_exchange_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "vip_change_category")
async def vip_change_category(callback: CallbackQuery):
    await vip_select_category(callback)

# ==================================================
# 6. РЕЙТИНГ
# ==================================================

@dp.callback_query(F.data.startswith("like_"))
async def like_video(callback: CallbackQuery):
    video_id = int(callback.data.replace("like_", ""))
    user_id = callback.from_user.id
    
    if user_has_voted(user_id, video_id):
        await callback.answer("❌ Ты уже голосовал!", show_alert=True)
        return
    
    update_rating(video_id, 'like')
    add_user_vote(user_id, video_id, 'like')
    
    likes, dislikes, rating = get_video_rating(video_id)
    await callback.message.edit_reply_markup(reply_markup=get_video_rating_keyboard(video_id, likes, dislikes))
    await callback.answer("✅ Лайк поставлен!")

@dp.callback_query(F.data.startswith("dislike_"))
async def dislike_video(callback: CallbackQuery):
    video_id = int(callback.data.replace("dislike_", ""))
    user_id = callback.from_user.id
    
    if user_has_voted(user_id, video_id):
        await callback.answer("❌ Ты уже голосовал!", show_alert=True)
        return
    
    update_rating(video_id, 'dislike')
    add_user_vote(user_id, video_id, 'dislike')
    
    likes, dislikes, rating = get_video_rating(video_id)
    await callback.message.edit_reply_markup(reply_markup=get_video_rating_keyboard(video_id, likes, dislikes))
    await callback.answer("👎 Дизлайк поставлен!")

@dp.callback_query(F.data.startswith("complaint_"))
async def complaint_video(callback: CallbackQuery):
    video_id = int(callback.data.replace("complaint_", ""))
    user_id = callback.from_user.id
    
    add_complaint(video_id, user_id)
    complaints = get_complaint_count(video_id)
    
    await callback.answer(f"📩 Жалоба принята! (жалоб: {complaints})", show_alert=True)
    
    if complaints >= 5:
        await bot.send_message(ADMIN_ID, f"⚠️ Видео #{video_id} получило {complaints} жалоб!")

# ==================================================
# 7. АДМИН-ПАНЕЛЬ
# ==================================================

@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только для админа!", show_alert=True)
        return
    await cmd_admin(callback.message)

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только для админа!", show_alert=True)
        return
    
    total_users, vip_users, today_users = get_user_stats()
    total_videos, good_videos, bad_videos, avg_rating = get_video_stats()
    
    cat_stats = get_category_stats()
    cat_text = "\n📁 <b>Категории:</b>\n"
    for cat_key, count in cat_stats.items():
        if count > 0:
            cat_data = CATEGORIES[cat_key]
            cat_text += f"• {cat_data['emoji']} {cat_data['name']}: {count}\n"
    
    text = f"""📊 <b>СТАТИСТИКА БАЗЫ</b>

👤 <b>Пользователи:</b>
• Всего: {total_users}
• VIP: {vip_users}
• За сегодня: {today_users}

🎬 <b>Видео:</b>
• Всего: {total_videos}
• С хорошим рейтингом (>= 5): {good_videos}
• С плохим рейтингом (< 5): {bad_videos}
• Средний рейтинг: {avg_rating}
{cat_text}"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👈 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "admin_vip_list")
async def admin_vip_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только для админа!", show_alert=True)
        return
    
    vip_users = get_vip_users()
    
    if not vip_users:
        await callback.answer("❌ Нет VIP пользователей!", show_alert=True)
        return
    
    text = "👑 <b>Список VIP пользователей</b>\n\n"
    for user_id, first_name, vip_until, duration in vip_users:
        days_left = (datetime.fromisoformat(vip_until) - datetime.now()).days
        text += f"• {first_name} (ID: {user_id})\n  До: {vip_until[:10]} | {duration}\n  Осталось: {days_left} дн.\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👈 Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "admin_cleanup")
async def admin_cleanup(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Только для админа!", show_alert=True)
        return
    
    deleted = auto_cleanup()
    
    await callback.answer(f"✅ Удалено {deleted} видео с рейтингом < {AUTO_DELETE_RATING}", show_alert=True)
    await callback.message.edit_text(
        f"🗑 Автоочистка завершена!\n\nУдалено: {deleted} видео\nВсего видео в базе: {get_video_count()}",
        reply_markup=get_admin_keyboard()
    )

# ==================================================
# 8. ВСЁ ОСТАЛЬНОЕ (В САМОМ КОНЦЕ!)
# ==================================================

@dp.message()
async def catch_all(message: Message):
    """Ловит всё, что не обработали другие хендлеры"""
    await message.answer(
        "📩 Я понимаю только ВИДЕО и команды!\n"
        "Отправь мне видео или нажми кнопку «Обменяться»."
    )
    print(f"📩 Неизвестное сообщение: {message.text if message.text else 'медиа'}")

# ==================================================
# 9. ФОН: ПРОВЕРКА VIP
# ==================================================

async def check_vip_expiring():
    while True:
        try:
            expiring = get_vip_expiring_soon()
            for user_id, first_name, vip_until in expiring:
                try:
                    await bot.send_message(
                        user_id,
                        f"""⚠️ <b>Ваша VIP-подписка истекает завтра!</b>

📅 Дата окончания: {vip_until[:10]}
⏳ Осталось: 1 день

💳 Продлите подписку сейчас через меню «👑 Купить VIP»"""
                    )
                except Exception as e:
                    logging.error(f"Ошибка отправки уведомления {user_id}: {e}")
        except Exception as e:
            logging.error(f"Ошибка проверки VIP: {e}")
        await asyncio.sleep(3600)

# ==================================================
# 10. ЗАПУСК
# ==================================================

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    
    print("=" * 60)
    print("🚀 БОТ ЗАПУЩЕН!")
    print("=" * 60)
    
    asyncio.create_task(check_vip_expiring())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("✅ Flask запущен в фоновом потоке!")
    asyncio.run(main())
