FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115,<1.0" \
    "httpx>=0.27,<1.0" \
    "pydantic>=2.8,<3.0" \
    "pydantic-settings>=2.4,<3.0" \
    "uvicorn[standard]>=0.30,<1.0" \
    "aiomysql>=0.2,<1.0" \
    "cryptography>=42,<47" \
    "redis>=5.0,<8.0"

# Run as an unprivileged user in containerized environments.
RUN useradd --create-home --uid 10001 appuser

COPY app ./app
COPY data/knowledge_base.json ./data/knowledge_base.json
COPY frontend ./frontend

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
