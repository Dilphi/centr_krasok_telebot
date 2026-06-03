import json
import sqlite3
from datetime import datetime

DB_PATH = "bot_data.db"

def migrate():
    """Мигрирует данные из JSON в SQLite."""
    try:
        # Подключаемся к БД
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Читаем JSON
        with open('bot_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Мигрируем пользователей и сообщения
        for user_id_str, history in data.get('conversation_history', {}).items():
            user_id = int(user_id_str)
            
            # Добавляем пользователя
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, last_activity, model)
                VALUES (?, ?, ?)
            ''', (user_id, datetime.now().isoformat(), 'gemini'))
            
            # Добавляем сообщения
            for msg in history:
                cursor.execute('''
                    INSERT INTO messages (user_id, role, content, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, msg['role'], msg['content'], datetime.now().isoformat()))
            
            print(f"✅ Мигрировано {len(history)} сообщений для user {user_id}")
        
        conn.commit()
        conn.close()
        print("🎉 Миграция завершена успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    migrate()