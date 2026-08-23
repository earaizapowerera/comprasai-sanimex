FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/data ./data
COPY frontend_static ./frontend_static

ENV ROOT_PATH=/comprasAI \
    COMPRASAI_DB_PATH=/app/data/comprasai.db \
    FRONTEND_STATIC_DIR=/app/frontend_static \
    AUTO_SEED_IF_MISSING=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --root-path \"$ROOT_PATH\""]
