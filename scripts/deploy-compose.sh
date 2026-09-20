#!/usr/bin/env sh
# Build and update the local/self-hosted Docker Compose deployment.
set -eu

compose() {
  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    docker compose "$@"
  fi
}

# `up --build` rebuilds changed layers and replaces the service without the
# avoidable downtime caused by `down`. Use `--pull` explicitly when updating
# base images rather than defeating the build cache on every deployment.
compose up -d --build --remove-orphans
compose ps
compose logs --tail=50
