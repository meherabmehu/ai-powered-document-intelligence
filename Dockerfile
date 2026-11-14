FROM node:22-slim AS frontend-build
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/app ./backend/app
COPY backend/migrations ./backend/migrations
COPY backend/alembic.ini ./backend/alembic.ini
RUN pip install --no-cache-dir ./backend
COPY --from=frontend-build /src/frontend/dist ./frontend/dist
COPY deploy/start.sh ./deploy/start.sh
RUN chmod +x ./deploy/start.sh
EXPOSE 10000
CMD ["./deploy/start.sh"]
