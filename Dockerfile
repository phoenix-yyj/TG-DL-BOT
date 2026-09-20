# Use uv from the official image and Python 3.11 slim for runtime.
FROM ghcr.io/astral-sh/uv:0.8.0 AS uv
FROM python:3.11-slim

# Set working directory
WORKDIR /app

COPY --from=uv /uv /uvx /bin/

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libc6-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency metadata first for better caching
COPY pyproject.toml uv.lock ./

# Install locked production dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p downloads sessions attached_assets

# Expose health check port
EXPOSE 3000

# Run the bot
CMD ["/app/.venv/bin/python", "main.py"]
