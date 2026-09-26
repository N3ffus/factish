FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.9.5 \
    && uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY backend ./backend
COPY migrations ./migrations
COPY content ./content
COPY frontend/dist ./frontend/dist

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m backend.import_content && exec uvicorn backend.app:app --host 0.0.0.0 --port 8000"]
