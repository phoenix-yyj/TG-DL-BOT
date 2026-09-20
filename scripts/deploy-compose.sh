#!/usr/bin/env sh
# Build and restart the local/self-hosted Docker Compose deployment.
set -eu

compose() {
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    docker compose "$@"
  fi
}

compose down
compose build --pull
compose up -d
compose ps
compose logs --tail=50
