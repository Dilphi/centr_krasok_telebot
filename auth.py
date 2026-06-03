# auth.py
import hashlib
import secrets
from datetime import datetime, timedelta
from database import (
    get_admin_by_username, 
    save_admin_session, 
    get_admin_session, 
    delete_admin_session, 
    update_admin_last_login, 
    create_admin, 
    get_all_admins
)

def hash_password(password: str) -> str:
    """Хэширует пароль."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль."""
    return hash_password(password) == password_hash

def generate_token() -> str:
    """Генерирует уникальный токен сессии."""
    return secrets.token_urlsafe(32)

def authenticate_user(username: str, password: str):
    """Аутентифицирует пользователя."""
    admin = get_admin_by_username(username)
    if admin and verify_password(password, admin["password_hash"]):
        update_admin_last_login(admin["id"])
        return admin
    return None

def create_session(admin_id: int) -> str:
    """Создаёт новую сессию."""
    token = generate_token()
    expires_at = (datetime.now() + timedelta(days=7)).isoformat()
    save_admin_session(admin_id, token, expires_at)
    return token

def validate_session(token: str):
    """Проверяет валидность сессии."""
    session = get_admin_session(token)
    if session:
        expires_at = datetime.fromisoformat(session["expires_at"])
        if expires_at > datetime.now():
            return session["admin_id"]
    return None

def logout(token: str):
    """Завершает сессию."""
    delete_admin_session(token)

def create_first_admin():
    """Создаёт первого администратора (если нет ни одного)."""
    admins = get_all_admins()
    if not admins:
        default_username = "admin"
        default_password = "2952"
        password_hash = hash_password(default_password)
        create_admin(default_username, password_hash)
        print(f"✅ Создан администратор по умолчанию: {default_username} / {default_password}")
        print("⚠️ Обязательно смените пароль после первого входа!")
        return True
    return False