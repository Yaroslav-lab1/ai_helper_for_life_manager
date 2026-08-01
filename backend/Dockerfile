FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY backend ./backend

EXPOSE 8000
CMD ["sh", "-c", "python -c 'from backend.config import settings; settings.validate_runtime()' && alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"]
