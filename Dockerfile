FROM python:3.13-slim
WORKDIR /app

COPY pyproject.toml uv.lock ./
# hadolint ignore=DL3013
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

COPY . .

CMD ["uv", "run", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
