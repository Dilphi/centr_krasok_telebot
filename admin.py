"""
Админ-панель для Telegram бота «Центр Красок #1»
Flask + Bootstrap + Авторизация
"""

import os
import json
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from dotenv import load_dotenv

from database import (
    get_all_users_dict, 
    get_user_messages_dict, 
    clear_user_history, 
    init_db, 
    save_user,
    get_all_admins,      
    delete_admin,       
    create_admin,       
    get_admin_by_username
)
from auth import (
    authenticate_user, 
    create_session, 
    validate_session, 
    logout,
    hash_password,
    create_first_admin
)

load_dotenv()

# Создаём Flask приложение
admin_app = Flask(__name__)
admin_app.secret_key = os.getenv("ADMIN_SECRET_KEY", "super-secret-key-change-it")
admin_app.config['SESSION_COOKIE_HTTPONLY'] = True
admin_app.config['SESSION_COOKIE_SECURE'] = False  # True для HTTPS
admin_app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Инициализируем базу данных
init_db()
create_first_admin()  # Создаём первого админа если нет

# Декоратор для проверки авторизации (по сессии)
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Пожалуйста, войдите в систему', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Декоратор для API авторизации
def require_auth(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or not authenticate_user(auth.username, auth.password):
            return jsonify({"error": "Unauthorized"}), 401
        return func(*args, **kwargs)
    return wrapper

# ==================== Страницы авторизации ====================

@admin_app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = authenticate_user(username, password)
        if admin:
            session['admin_id'] = admin['id']
            session['admin_username'] = admin['username']
            flash(f'Добро пожаловать, {username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль', 'danger')
    
    return render_template('admin/login.html')

@admin_app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация нового администратора."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Валидация
        if not username or not password:
            flash('Заполните все поля', 'danger')
            return render_template('admin/register.html')
        
        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return render_template('admin/register.html')
        
        if len(password) < 6:
            flash('Пароль должен быть не менее 6 символов', 'danger')
            return render_template('admin/register.html')
        
        # Проверяем, не существует ли уже пользователь
        from database import get_admin_by_username
        existing = get_admin_by_username(username)
        if existing:
            flash('Пользователь с таким именем уже существует', 'danger')
            return render_template('admin/register.html')
        
        # Создаём администратора
        password_hash = hash_password(password)
        create_admin(username, password_hash)
        
        flash('Регистрация успешна! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))
    
    return render_template('admin/register.html')

@admin_app.route('/logout')
def logout_route():
    """Выход из системы."""
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

# ==================== Страницы админ-панели ====================

@admin_app.route('/')
@login_required
def index():
    """Главная страница админ-панели."""
    update_stats()
    return render_template('admin/index.html', stats=stats, admin_username=session.get('admin_username'))

@admin_app.route('/users')
@login_required
def users():
    """Список пользователей из БД."""
    db_users = get_all_users_dict()
    
    users_list = []
    for user in db_users:
        user_id = user["user_id"]
        last_activity = user.get("last_activity")
        model = user.get("model", "gemini")
        
        messages = get_user_messages_dict(user_id)
        messages_count = len(messages)
        
        users_list.append({
            "id": user_id,
            "last_active": last_activity if last_activity else "Неизвестно",
            "model": model.upper(),
            "messages": messages_count,
            "is_active": False
        })
    
    users_list.sort(key=lambda x: x["last_active"], reverse=True)
    
    return render_template('admin/users.html', users=users_list, admin_username=session.get('admin_username'))

@admin_app.route('/conversations/<int:user_id>')
@login_required
def conversations(user_id):
    """История диалога пользователя из БД."""
    messages = get_user_messages_dict(user_id)
    
    history = []
    for msg in messages:
        history.append({
            "role": msg.get("role", "unknown"),
            "content": msg.get("content", ""),
            "timestamp": msg.get("timestamp", "")
        })
    
    return render_template('admin/conversations.html', 
                          user_id=user_id, 
                          history=history,
                          last_active=None,
                          model="gemini",
                          admin_username=session.get('admin_username'))

@admin_app.route('/stats')
@login_required
def stats_page():
    """Страница со статистикой."""
    update_stats()
    return render_template('admin/stats.html', stats=stats, admin_username=session.get('admin_username'))

@admin_app.route('/admins')
@login_required
def admins_list():
    """Список администраторов."""
    admins = get_all_admins()
    return render_template('admin/admins.html', admins=admins, admin_username=session.get('admin_username'))

@admin_app.route('/admins/delete/<int:admin_id>', methods=['POST'])
@login_required
def delete_admin_route(admin_id):
    """Удаление администратора."""
    if admin_id == session.get('admin_id'):
        flash('Нельзя удалить самого себя', 'danger')
        return redirect(url_for('admins_list'))
    
    delete_admin(admin_id)
    flash('Администратор удалён', 'success')
    return redirect(url_for('admins_list'))

# ==================== API (с авторизацией) ====================

@admin_app.route('/api/conversations/<int:user_id>/clear', methods=['POST'])
@require_auth
def clear_conversation(user_id):
    clear_user_history(user_id)
    return jsonify({"success": True, "message": "История очищена"})

@admin_app.route('/api/user/<int:user_id>/model', methods=['POST'])
@require_auth
def change_user_model(user_id):
    data = request.get_json()
    new_model = data.get("model")
    
    if new_model in ["gemini", "groq"]:
        save_user(user_id, new_model)
        return jsonify({"success": True, "message": f"Модель изменена на {new_model}"})
    return jsonify({"success": False, "message": "Неверная модель"})

@admin_app.route('/api/stats', methods=['GET'])
@require_auth
def api_stats():
    update_stats()
    return jsonify(stats)

@admin_app.route('/api/users', methods=['GET'])
@require_auth
def api_users():
    db_users = get_all_users_dict()
    users_list = []
    for user in db_users:
        users_list.append({
            "id": user["user_id"],
            "last_active": user.get("last_activity"),
            "model": user.get("model", "gemini"),
            "messages": len(get_user_messages_dict(user["user_id"]))
        })
    return jsonify(users_list)

# ==================== Вспомогательные функции ====================

def update_stats():
    """Обновляет статистику из БД."""
    global stats
    db_users = get_all_users_dict()
    
    stats["total_users"] = len(db_users)
    
    today = datetime.now().date()
    active_today = 0
    for user in db_users:
        last_activity = user.get("last_activity")
        if last_activity:
            try:
                last_date = datetime.fromisoformat(last_activity).date()
                if last_date == today:
                    active_today += 1
            except:
                pass
    stats["active_today"] = active_today
    
    gemini_count = sum(1 for user in db_users if user.get("model") == "gemini")
    groq_count = sum(1 for user in db_users if user.get("model") == "groq")
    stats["model_distribution"] = {"gemini": gemini_count, "groq": groq_count}
    
    total_msgs = 0
    for user in db_users:
        user_id = user["user_id"]
        messages = get_user_messages_dict(user_id)
        total_msgs += len(messages)
    stats["total_messages"] = total_msgs

stats = {
    "total_users": 0,
    "active_today": 0,
    "total_messages": 0,
    "total_photos": 0,
    "model_distribution": {"gemini": 0, "groq": 0}
}

if __name__ == '__main__':
    admin_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)