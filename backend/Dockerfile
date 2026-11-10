# Research API for live Pull (any NSE symbol). Holds no personal data.
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/finn ./finn
COPY data ./data_seed
ENV FINN_DATA_DIR=/app/data FINN_OUT_DIR=/app/out PYTHONUNBUFFERED=1
# seed registry + build-time cache; runtime cache lives in /app/data/cache
RUN mkdir -p /app/data && cp -r /app/data_seed/. /app/data/
EXPOSE 8000
CMD ["sh", "-c", "uvicorn finn.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
