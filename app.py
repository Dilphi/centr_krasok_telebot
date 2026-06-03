"""
Telegram AI-бот «Центр Красок #1»
Стек: aiogram 3.x · Groq + Gemini · python-dotenv · Pillow · python-pptx
Бот работает без команд — только текстовые сообщения и фото.
"""

import asyncio
from database import save_user, save_message, init_db
import time
import base64
import io
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
import os
from aiogram.exceptions import TelegramForbiddenError

from dotenv import load_dotenv
from PIL import Image

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.enums import ParseMode, ChatAction
from aiogram.client.default import DefaultBotProperties

from groq import AsyncGroq, APIError as GroqAPIError
import google.generativeai as genai

from company_data import COMPANY_KNOWLEDGE
import json
import threading

current_ai_provider = "gemini"
last_gemini_error_time = None

# Загрузка переменных окружения
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Проверка конфигурации
def check_config():
    """Проверяет наличие необходимых переменных окружения."""
    missing = []
    if not TELEGRAM_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    
    if missing:
        raise RuntimeError(
            f"Отсутствуют переменные окружения: {', '.join(missing)}\n"
            "Скопируйте env.example в .env и заполните значения."
        )

check_config()

# Инициализация клиентов
groq_client = AsyncGroq(api_key=GROQ_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)

# Настройки моделей
GROQ_MODEL = "llama-3.1-8b-instant"
GEMINI_MODEL = "gemini-2.5-flash"

# Логирование
def sanitize_log(text: str, max_len: int = 100) -> str:
    """Очищает текст от потенциально чувствительных данных для логов."""
    text = re.sub(r'\+\d[\d\s\(\)\-]{8,}\d', '[PHONE]', text)
    return text[:max_len]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("centr_krasok_bot")

# Системный промпт
SYSTEM_PROMPT = f"""Ты — дружелюбный и профессиональный AI-ассистент интернет-магазина
«Центр Красок #1» в Казахстане.

ТВОЯ ЗАДАЧА:
- Отвечать на вопросы клиентов о компании, товарах, брендах, доставке, ценах, адресах.
- Давать точные, краткие и полезные ответы строго на основе базы знаний ниже.

СТРОГИЕ ПРАВИЛА:
1. Отвечай ТОЛЬКО на основе базы знаний. Не придумывай факты, цены, бренды или адреса.
2. Если вопрос не по теме компании или ремонта — вежливо перенаправь на тематику магазина.
3. Если нужной информации нет в базе — честно скажи и предложи позвонить: +7 (777) 292-84-01.
4. Отвечай на языке вопроса (русский, казахский, английский).
5. Используй эмодзи умеренно.
6. Не консультируй по медицине, политике и другим несмежным темам.
7. Если пользователь присылает фото — опиши, что видишь, и предложи подходящие краски/материалы
   из ассортимента компании (если это уместно).

БАЗА ЗНАНИЙ:
{COMPANY_KNOWLEDGE}
"""

# Хранилище истории диалогов
conversation_history: dict[int, list[dict]] = defaultdict(list)
last_activity: dict[int, datetime] = {}

MAX_HISTORY = 12
INACTIVITY_RESET = timedelta(minutes=30)

# Rate limiting
rate_limit_log: dict[int, list[datetime]] = defaultdict(list)
RATE_MAX = 10
RATE_WINDOW = timedelta(minutes=1)
MAX_MESSAGE_LENGTH = 4096
MAX_PHOTO_SIZE = 20 * 1024 * 1024

# Текущая модель для каждого пользователя (если используется)
user_model: dict[int, str] = defaultdict(lambda: "gemini")

DATA_FILE = "bot_data.json"

def save_data_to_file():
    """Сохраняет данные бота в файл для админ-панели."""
    data = {
        "conversation_history": {},
        "last_activity": {},
        "user_model": {},
        "rate_limit_log": {},
        "timestamp": datetime.now().isoformat()
    }
    
    for uid, history in conversation_history.items():
        data["conversation_history"][str(uid)] = history
    
    for uid, activity in last_activity.items():
        if isinstance(activity, datetime):
            data["last_activity"][str(uid)] = activity.isoformat()
    
    for uid, model in user_model.items():
        data["user_model"][str(uid)] = model
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def periodic_save():
    """Периодически сохраняет данные в файл."""
    import time
    while True:
        time.sleep(30)
        save_data_to_file()
        logger.info("Данные сохранены в файл")


def check_rate_limit(user_id: int) -> bool:
    """Проверяет не превысил ли пользователь лимит сообщений."""
    now = datetime.now()
    cutoff = now - RATE_WINDOW
    rate_limit_log[user_id] = [t for t in rate_limit_log[user_id] if t > cutoff]
    if len(rate_limit_log[user_id]) >= RATE_MAX:
        return False
    rate_limit_log[user_id].append(now)
    return True


def get_history(user_id: int) -> list[dict]:
    """Возвращает историю диалога; сбрасывает при таймауте."""
    now = datetime.now()
    if user_id in last_activity:
        if now - last_activity[user_id] > INACTIVITY_RESET:
            conversation_history[user_id] = []
            logger.info(f"История сброшена (таймаут) user={user_id}")
    last_activity[user_id] = now
    
    # Сохраняем пользователя в БД
    save_user(user_id, user_model.get(user_id, "gemini"))
    
    return conversation_history[user_id]


def compress_image_to_base64(image_bytes: bytes, max_size: int = 1024) -> str:
    """Сжимает изображение и возвращает base64-строку."""
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > max_size:
        ratio = max_size / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


# AI-ответ через Gemini (текст)
async def get_gemini_response(user_id: int, user_text: str, history: list[dict]) -> str:
    """Получает ответ от Gemini на текстовый запрос."""
    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT
        )
        
        gemini_history = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]
            if isinstance(content, str):
                gemini_history.append({"role": role, "parts": [content]})
        
        chat = model.start_chat(history=gemini_history)
        response = await chat.send_message_async(user_text)
        return response.text or "⚠️ Не удалось получить ответ."
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return "⚠️ Ошибка Gemini API. Попробуйте позже."


# AI-ответ через Gemini Vision (фото)
async def get_gemini_vision_response(user_id: int, image_b64: str, caption: str) -> str:
    """Получает ответ от Gemini на запрос с фотографией."""
    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT
        )
        
        image_bytes = base64.b64decode(image_b64)
        image = Image.open(io.BytesIO(image_bytes))
        user_text = caption or "Что на фото? Порекомендуй подходящие материалы из нашего магазина."
        
        response = await model.generate_content_async([user_text, image])
        
        if response.text:
            return response.text
        else:
            return "⚠️ Не удалось распознать изображение. Попробуйте прислать более чёткое фото или опишите словами."
            
    except Exception as e:
        logger.error(f"Gemini Vision error: {e}")
        return "⚠️ Ошибка обработки фото. Попробуйте ещё раз или позвоните: +7 (777) 292-84-01"


# AI-ответ через Groq (быстрый, только текст)
async def get_groq_response(user_id: int, user_text: str, history: list[dict]) -> str:
    """Получает ответ от Groq на текстовый запрос."""
    try:
        resp = await groq_client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=1024,
            temperature=0.7,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        )
        return resp.choices[0].message.content or "⚠️ Не удалось получить ответ."
    except GroqAPIError as e:
        logger.error(f"Groq APIError: {e}")
        return "⚠️ Ошибка Groq API. Попробуйте позже."
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return "⚠️ Ошибка при обращении к Groq."
    
# Главная функция получения ответа с автоматическим переключением
async def get_ai_response(user_id: int, user_text: str) -> str:
    """Получает ответ от AI с автоматическим переключением на Groq при ошибке Gemini."""
    global current_ai_provider, last_gemini_error_time
    
    history = get_history(user_id)
    history.append({"role": "user", "content": user_text})
    
    # Сохраняем сообщение пользователя в БД
    save_message(user_id, "user", user_text)

    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
        conversation_history[user_id] = history

    # Пытаемся получить ответ от текущего провайдера
    reply = None
    
    if current_ai_provider == "gemini":
        reply = await get_gemini_response(user_id, user_text, history)
        # Проверяем, не вернула ли Gemini ошибку
        if reply and "Ошибка Gemini API" in reply:
            logger.warning("Gemini API ошибка, переключаемся на Groq")
            current_ai_provider = "groq"
            last_gemini_error_time = datetime.now()
            # Повторяем запрос через Groq
            reply = await get_groq_response(user_id, user_text, history)
    else:
        reply = await get_groq_response(user_id, user_text, history)
    
    history.append({"role": "assistant", "content": reply})
    
    # Сохраняем ответ бота в БД
    save_message(user_id, "assistant", reply)
    
    # Если прошло больше часа с последней ошибки Gemini, пробуем вернуться
    if current_ai_provider == "groq" and last_gemini_error_time:
        if datetime.now() - last_gemini_error_time > timedelta(hours=1):
            logger.info("Пробуем вернуться на Gemini")
            current_ai_provider = "gemini"
    
    return reply


# Bot & Dispatcher
bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


# /start — единственная команда
@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Обработчик команды /start."""
    try:
        user_name = message.from_user.first_name or "друг"
        user_id = message.from_user.id
        conversation_history[user_id] = []
        last_activity[user_id] = datetime.now()

        await message.answer(
            f"👋 Привет, <b>{user_name}</b>!\n\n"
            "🎨 Я — AI-ассистент магазина <b>«Центр Красок #1»</b>.\n\n"
            "Могу ответить на вопросы о:\n"
            "• красках, лаках, штукатурках и инструментах\n"
            "• брендах и акциях\n"
            "• адресах и доставке\n"
            "• услугах для дизайнеров и строителей\n\n"
            "📸 Отправьте <b>фото помещения</b> — подберу подходящие материалы!\n\n"
            "Просто напишите вопрос! ✍️\n\n"
            "📞 <b>+7 (777) 292-84-01</b> · Пн–Вс 10:00–20:00"
        )
    except TelegramForbiddenError:
        # Пользователь заблокировал бота — просто игнорируем
        logger.warning(f"User {message.from_user.id} blocked the bot")
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}")


# Текстовые сообщения
@dp.message(F.text)
async def handle_text(message: Message) -> None:
    """Обработчик текстовых сообщений."""
    user_id = message.from_user.id
    user_text = message.text.strip()

    if not user_text:
        return

    if len(user_text) > MAX_MESSAGE_LENGTH:
        await message.answer(
            f"⚠️ Сообщение слишком длинное ({len(user_text)} символов). "
            f"Пожалуйста, сократите до {MAX_MESSAGE_LENGTH} символов."
        )
        return

    if not check_rate_limit(user_id):
        await message.answer("⏳ Слишком много запросов. Подождите немного.")
        return

    logger.info(f"[TEXT] user={user_id}: {sanitize_log(user_text)}")
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    reply = await get_ai_response(user_id, user_text)
    logger.info(f"[REPLY] → {reply[:80]}")
    await message.answer(reply)


# Фото
@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Обработчик фотографий."""
    global current_ai_provider, last_gemini_error_time  # ← В САМОМ НАЧАЛЕ ФУНКЦИИ
    
    user_id = message.from_user.id

    if not check_rate_limit(user_id):
        await message.answer("⏳ Слишком много запросов. Подождите немного.")
        return

    # Если сейчас используется Groq, предупреждаем
    if current_ai_provider == "groq":
        await message.answer(
            "⚠️ Сейчас используется быстрая модель Groq, которая не поддерживает анализ фото.\n\n"
            "Для анализа фото дождитесь восстановления Gemini или попробуйте позже.\n\n"
            "А пока опишите словами, что видите на фото, и я помогу! 🎨"
        )
        return

    photo = message.photo[-1]
    if photo.file_size > MAX_PHOTO_SIZE:
        await message.answer(
            f"⚠️ Фото слишком большое ({photo.file_size // 1024 // 1024} MB). "
            f"Максимальный размер: {MAX_PHOTO_SIZE // 1024 // 1024} MB"
        )
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    try:
        file = await bot.get_file(photo.file_id)
        
        from io import BytesIO
        downloaded = BytesIO()
        await bot.download_file(file.file_path, destination=downloaded)
        image_bytes = downloaded.getvalue()
        
        image_b64 = compress_image_to_base64(image_bytes)
        caption = message.caption or ""
        logger.info(f"[PHOTO] user={user_id}, size={len(image_bytes)} bytes")

        reply = await get_gemini_vision_response(user_id, image_b64, caption)
        
        # Если Gemini вернул ошибку, переключаемся
        if reply and ("Ошибка" in reply or "Gemini" in reply):
            current_ai_provider = "groq"
            last_gemini_error_time = datetime.now()
            await message.answer(
                "⚠️ Анализ фото временно недоступен.\n"
                "Переключаюсь на текстовый режим. Задайте вопрос текстом! 📝"
            )
        else:
            await message.answer(reply)
        
    except Exception as e:
        logger.error(f"Photo processing error: {e}")
        await message.answer(
            "⚠️ Не удалось обработать фото.\n\n"
            "Пожалуйста, опишите словами, что видите на фото, "
            "и я порекомендую подходящие материалы! 🎨"
        )

        
# Функция для запуска Flask админ-панели
def run_flask():
    """Запускает Flask админ-панель в отдельном потоке."""
    try:
        from admin import admin_app
        logger.info("🌐 Админ-панель запущена на http://localhost:5000")
        admin_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Ошибка запуска админ-панели: {e}")

# Главная функция запуска бота
async def main() -> None:
    """Главная функция запуска бота и админ-панели."""
    # Инициализируем базу данных
    init_db()
    logger.info("📁 База данных инициализирована")
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем периодическое сохранение данных
    save_thread = threading.Thread(target=periodic_save, daemon=True)
    save_thread.start()
    
    logger.info("🚀 Запуск бота «Центр Красок #1»...")
    logger.info(f"📡 Модель: Gemini ({GEMINI_MODEL})")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())