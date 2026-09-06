FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend ./backend
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
RUN useradd --create-home --uid 10001 platform && mkdir -p /app/storage && chown -R platform:platform /app
USER platform
EXPOSE 8000
CMD ["uvicorn", "platform_app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
