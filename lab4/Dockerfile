# Используем официальный образ Python 3.12 в качестве базового
FROM python:3.12-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt /app/requirements.txt

# Устанавливаем зависимости из requirements.txt и py-spy
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir py-spy

# Копируем файл из приложения в контейнер
COPY search.py /app/search.py

# Указываем команду для запуска приложения FastAPI с использованием Uvicorn
CMD ["python", "-m", "uvicorn", "search:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
