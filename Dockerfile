FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock LICENSE README.md ./

ARG EXTRAS=""

# Install dependencies first (cached unless pyproject.toml/uv.lock change)
RUN if [ -z "$EXTRAS" ]; then \
      uv sync --frozen --no-dev --no-install-project; \
    else \
      uv sync --frozen --no-dev --no-install-project --extra "$EXTRAS"; \
    fi

COPY src/ src/

RUN if [ -z "$EXTRAS" ]; then \
      uv sync --frozen --no-dev --no-editable; \
    else \
      uv sync --frozen --no-dev --no-editable --extra "$EXTRAS"; \
    fi

FROM python:3.11-slim

RUN groupadd --system was && useradd --system --gid was was

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

USER was

EXPOSE 8080

CMD ["uvicorn", "was_server:app", "--host", "0.0.0.0", "--port", "8080"]
