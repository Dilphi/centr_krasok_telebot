# database.py
import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager
import logging

logger = logging.getLogger("centr_krasok_bot")

DB_PATH = "bot_data.db"

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    """Инициализирует базу данных."""
    try:
        with get_db() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    last_activity TEXT,
                    model TEXT DEFAULT 'gemini'
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    timestamp TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS rate_limit (
                    user_id INTEGER,
                    timestamp TEXT
                )
            ''')
        logger.info("✅ База данных инициализирована успешно")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

def save_user(user_id: int, model: str = "gemini"):
    """Сохраняет или обновляет пользователя."""
    try:
        with get_db() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO users (user_id, model, last_activity)
                VALUES (?, ?, ?)
            ''', (user_id, model, datetime.now().isoformat()))
            logger.info(f"✅ Пользователь {user_id} сохранён в БД")
            return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения пользователя {user_id}: {e}")
        return False

def save_message(user_id: int, role: str, content: str):
    """Сохраняет сообщение в базу."""
    try:
        with get_db() as conn:
            conn.execute('''
                INSERT INTO messages (user_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (user_id, role, content, datetime.now().isoformat()))
            # Обновляем последнюю активность
            conn.execute('''
                UPDATE users SET last_activity = ? WHERE user_id = ?
            ''', (datetime.now().isoformat(), user_id))
            logger.info(f"✅ Сообщение от user={user_id} сохранено в БД")
            return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения сообщения: {e}")
        return False

def get_all_users():
    """Получает всех пользователей."""
    try:
        with get_db() as conn:
            result = conn.execute('SELECT * FROM users ORDER BY last_activity DESC').fetchall()
            logger.info(f"📊 Получено {len(result)} пользователей из БД")
            return result
    except Exception as e:
        logger.error(f"❌ Ошибка получения пользователей: {e}")
        return []

def get_all_users_dict():
    """Получает всех пользователей в виде списка словарей."""
    with get_db() as conn:
        users = conn.execute('SELECT * FROM users ORDER BY last_activity DESC').fetchall()
        return [dict(user) for user in users]

def get_user_messages_dict(user_id: int):
    """Получает сообщения пользователя в виде списка словарей."""
    with get_db() as conn:
        messages = conn.execute('''
            SELECT * FROM messages WHERE user_id = ? ORDER BY timestamp
        ''', (user_id,)).fetchall()
        return [dict(msg) for msg in messages]

def get_user_messages(user_id: int):
    """Получает сообщения пользователя."""
    try:
        with get_db() as conn:
            result = conn.execute('''
                SELECT * FROM messages WHERE user_id = ? ORDER BY timestamp
            ''', (user_id,)).fetchall()
            logger.info(f"💬 Получено {len(result)} сообщений для user={user_id}")
            return result
    except Exception as e:
        logger.error(f"❌ Ошибка получения сообщений: {e}")
        return []

def clear_user_history(user_id: int):
    """Очищает историю пользователя."""
    try:
        with get_db() as conn:
            conn.execute('DELETE FROM messages WHERE user_id = ?', (user_id,))
            logger.info(f"🗑 История пользователя {user_id} очищена")
            return True
    except Exception as e:
        logger.error(f"❌ Ошибка очистки истории: {e}")
        return False


def init_admin_db():
    """Инициализирует таблицу администраторов."""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT,
                last_login TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS admin_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                token TEXT UNIQUE,
                created_at TEXT,
                expires_at TEXT,
                FOREIGN KEY (admin_id) REFERENCES admins (id)
            )
        ''')

def create_admin(username: str, password_hash: str):
    """Создаёт нового администратора."""
    with get_db() as conn:
        conn.execute('''
            INSERT INTO admins (username, password_hash, created_at)
            VALUES (?, ?, ?)
        ''', (username, password_hash, datetime.now().isoformat()))

def get_admin_by_username(username: str):
    """Получает администратора по имени."""
    with get_db() as conn:
        result = conn.execute('SELECT * FROM admins WHERE username = ?', (username,)).fetchone()
        return dict(result) if result else None

def get_admin_by_id(admin_id: int):
    """Получает администратора по ID."""
    with get_db() as conn:
        result = conn.execute('SELECT * FROM admins WHERE id = ?', (admin_id,)).fetchone()
        return dict(result) if result else None

def save_admin_session(admin_id: int, token: str, expires_at: str):
    """Сохраняет сессию администратора."""
    with get_db() as conn:
        conn.execute('''
            INSERT INTO admin_sessions (admin_id, token, created_at, expires_at)
            VALUES (?, ?, ?, ?)
        ''', (admin_id, token, datetime.now().isoformat(), expires_at))

def get_admin_session(token: str):
    """Получает сессию по токену."""
    with get_db() as conn:
        result = conn.execute('SELECT * FROM admin_sessions WHERE token = ?', (token,)).fetchone()
        return dict(result) if result else None

def delete_admin_session(token: str):
    """Удаляет сессию (выход)."""
    with get_db() as conn:
        conn.execute('DELETE FROM admin_sessions WHERE token = ?', (token,))

def update_admin_last_login(admin_id: int):
    """Обновляет время последнего входа."""
    with get_db() as conn:
        conn.execute('UPDATE admins SET last_login = ? WHERE id = ?', (datetime.now().isoformat(), admin_id))

def get_all_admins():
    """Получает всех администраторов."""
    with get_db() as conn:
        result = conn.execute('SELECT id, username, created_at, last_login FROM admins').fetchall()
        return [dict(r) for r in result]

def delete_admin(admin_id: int):
    """Удаляет администратора."""
    with get_db() as conn:
        conn.execute('DELETE FROM admins WHERE id = ?', (admin_id,))

# Инициализируем таблицы админов при запуске
init_admin_db()