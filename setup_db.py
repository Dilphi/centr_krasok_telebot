#!/usr/bin/env python3
"""
Универсальный скрипт для инициализации и миграции базы данных
Запускается один раз при первом запуске бота
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = "bot_data.db"
JSON_PATH = "bot_data.json"

def init_db():
    """Инициализирует базу данных (создаёт таблицы)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Создаём таблицы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_activity TEXT,
            model TEXT DEFAULT 'gemini'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rate_limit (
            user_id INTEGER,
            timestamp TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Таблицы созданы/проверены")

def migrate_from_json():
    """Переносит данные из JSON в SQLite."""
    if not os.path.exists(JSON_PATH):
        print("⚠️ JSON файл не найден, миграция не требуется")
        return False
    
    try:
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        conversation_history = data.get('conversation_history', {})
        
        if not conversation_history:
            print("⚠️ Нет данных для миграции")
            return False
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        migrated_count = 0
        
        for user_id_str, history in conversation_history.items():
            user_id = int(user_id_str)
            
            # Проверяем, есть ли уже пользователь
            cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            exists = cursor.fetchone()
            
            if not exists:
                # Добавляем пользователя
                cursor.execute('''
                    INSERT INTO users (user_id, last_activity, model)
                    VALUES (?, ?, ?)
                ''', (user_id, datetime.now().isoformat(), 'gemini'))
                print(f"  👤 Добавлен пользователь {user_id}")
            
            # Добавляем сообщения
            for msg in history:
                cursor.execute('''
                    INSERT INTO messages (user_id, role, content, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, msg['role'], msg['content'], datetime.now().isoformat()))
                migrated_count += 1
            
            print(f"  💬 Добавлено {len(history)} сообщений для user {user_id}")
        
        conn.commit()
        conn.close()
        
        print(f"\n✅ Миграция завершена! Перенесено {migrated_count} сообщений")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")
        return False

def check_db():
    """Проверяет содержимое базы данных."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Считаем пользователей
    cursor.execute('SELECT COUNT(*) FROM users')
    users_count = cursor.fetchone()[0]
    
    # Считаем сообщения
    cursor.execute('SELECT COUNT(*) FROM messages')
    messages_count = cursor.fetchone()[0]
    
    conn.close()
    
    print(f"\n📊 Статистика базы данных:")
    print(f"   👥 Пользователей: {users_count}")
    print(f"   💬 Сообщений: {messages_count}")
    
    return users_count, messages_count

def show_users():
    """Показывает список пользователей."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_id, last_activity, model FROM users ORDER BY last_activity DESC')
    users = cursor.fetchall()
    
    conn.close()
    
    if users:
        print(f"\n👥 Список пользователей:")
        for user in users:
            print(f"   ID: {user[0]}, Модель: {user[2]}, Активность: {user[1][:19] if user[1] else 'Нет'}")
    else:
        print("\n⚠️ Пользователей пока нет")

def main():
    """Главная функция."""
    print("=" * 50)
    print("🚀 Универсальный скрипт инициализации БД")
    print("=" * 50)
    
    # 1. Инициализируем БД (создаём таблицы)
    print("\n1️⃣ Инициализация базы данных...")
    init_db()
    
    # 2. Проверяем, есть ли данные в JSON и переносим их
    print("\n2️⃣ Проверка и миграция из JSON...")
    migrate_from_json()
    
    # 3. Проверяем содержимое БД
    print("\n3️⃣ Проверка базы данных...")
    check_db()
    
    # 4. Показываем пользователей
    show_users()
    
    print("\n" + "=" * 50)
    print("✅ Готово! База данных настроена.")
    print("💡 Теперь можно запускать бота: python3 app.py")
    print("=" * 50)

if __name__ == "__main__":
    main()