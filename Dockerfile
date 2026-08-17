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
    "cryptography>=42,<47"

COPY app ./app
COPY data/knowledge_base.json ./data/knowledge_base.json

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
