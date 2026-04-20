FROM python:3.13-slim
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
# hadolint ignore=DL3013
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

COPY . .

RUN useradd -m appuser && mkdir -p /app/data && chown -R appuser:appuser /app/data
USER appuser

CMD [".venv/bin/uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
