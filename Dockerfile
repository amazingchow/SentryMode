FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Install production dependencies into the project virtualenv.
RUN uv sync --frozen --no-dev

# Default behavior: start the shared monitoring loop.
CMD ["uv", "run", "sentrymode", "list-factors"]
