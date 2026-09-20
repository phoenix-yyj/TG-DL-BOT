#!/usr/bin/env sh
# Pull the selected GHCR image and update the Docker Compose deployment.
set -eu

compose() {
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    docker compose "$@"
  fi
}

compose pull telegram-bot
compose up -d --remove-orphans
compose ps
compose logs --tail=50
