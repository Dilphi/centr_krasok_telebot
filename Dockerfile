# Dockerfile
FROM python:3.11-slim

# Установка рабочей директории
WORKDIR /app

# Копирование зависимостей
COPY requirements.txt .

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование всех файлов проекта
COPY . .

# Переменные окружения (будут переданы через docker-compose или -e)
ENV PYTHONUNBUFFERED=1

# Команда запуска
CMD ["python", "app.py"]