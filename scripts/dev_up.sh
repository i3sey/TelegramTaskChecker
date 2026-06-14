#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if command -v docker-compose >/dev/null 2>&1; then
  compose() {
    docker-compose "$@"
  }
elif docker compose version >/dev/null 2>&1; then
  compose() {
    docker compose "$@"
  }
else
  echo "Docker Compose is not installed. Install it first (see instructions in the response)." >&2
  exit 1
fi

cleanup() {
  compose -f "$ROOT_DIR/docker-compose.yml" down
}

trap cleanup INT TERM EXIT

echo "Starting PostgreSQL and Redis..."
compose -f "$ROOT_DIR/docker-compose.yml" up -d postgres redis

echo "Building bot and web images..."
compose -f "$ROOT_DIR/docker-compose.yml" build bot web

echo "Resetting database..."
compose -f "$ROOT_DIR/docker-compose.yml" run --rm bot python scripts/reset_db.py

echo "Starting bot and web..."
compose -f "$ROOT_DIR/docker-compose.yml" up bot web
