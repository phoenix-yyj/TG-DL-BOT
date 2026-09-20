# Keep uv pinned so dependency installation is reproducible across builds.
FROM astral/uv:0.12.17 AS uv

FROM python:3.11-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY --from=uv /uv /uvx /bin/

# TgCrypto ships a CPython 3.11 x86_64 wheel; arm64 needs its C extension built.
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "arm64" ]; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Install dependencies before copying frequently changing application files.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY main.py ./
COPY core ./core

FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/main.py ./main.py
COPY --from=builder /app/core ./core

RUN mkdir -p downloads sessions attached_assets

CMD ["python", "main.py"]
