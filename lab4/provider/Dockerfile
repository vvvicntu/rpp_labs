# Используем официальный образ Python 3.12 в качестве базового
FROM python:3.12-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Устанавливаем зависимости
RUN pip install --no-cache-dir fastapi uvicorn

# Копируем provider.py в контейнер
COPY provider.py /app/provider.py

# Указываем команду для запуска приложения FastAPI с использованием Uvicorn
CMD ["python", "-m", "uvicorn", "provider:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
