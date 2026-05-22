#!/bin/sh
set -eu

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-telegram_task_checker}"
POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_DB="${REDIS_DB:-0}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

export POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB POSTGRES_HOST POSTGRES_PORT PGDATA
export REDIS_HOST REDIS_PORT REDIS_DB REDIS_PASSWORD

POSTGRES_STARTED=0
REDIS_STARTED=0

find_pg_bin() {
  binary_name="$1"

  if command -v "$binary_name" >/dev/null 2>&1; then
    command -v "$binary_name"
    return 0
  fi

  for candidate in /usr/lib/postgresql/*/bin/"$binary_name"; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done

  echo "$binary_name"
}

INITDB_BIN="$(find_pg_bin initdb)"
PG_CTL_BIN="$(find_pg_bin pg_ctl)"
PSQL_BIN="$(find_pg_bin psql)"
CREATEDB_BIN="$(find_pg_bin createdb)"

is_local_host() {
  case "$1" in
    localhost|127.0.0.1)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

wait_for_postgres() {
  attempts=0
  until PGPASSWORD="$POSTGRES_PASSWORD" "$PSQL_BIN" \
    -h "$POSTGRES_HOST" \
    -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -c "SELECT 1" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 30 ]; then
      echo "PostgreSQL did not become ready in time" >&2
      return 1
    fi
    sleep 1
  done
}

wait_for_redis() {
  attempts=0
  while :; do
    if [ -n "$REDIS_PASSWORD" ]; then
      if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" ping >/dev/null 2>&1; then
        break
      fi
    else
      if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping >/dev/null 2>&1; then
        break
      fi
    fi

    attempts=$((attempts + 1))
    if [ "$attempts" -ge 30 ]; then
      echo "Redis did not become ready in time" >&2
      return 1
    fi
    sleep 1
  done
}

start_local_postgres() {
  mkdir -p "$PGDATA" /var/run/postgresql /var/log/postgresql
  chown -R postgres:postgres "$PGDATA" /var/run/postgresql /var/log/postgresql
  chmod 700 "$PGDATA"
  chmod 775 /var/run/postgresql

  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    PASSWORD_FILE="$(mktemp)"
    trap 'rm -f "$PASSWORD_FILE"' EXIT
    printf "%s" "$POSTGRES_PASSWORD" > "$PASSWORD_FILE"
    chown postgres:postgres "$PASSWORD_FILE"
    chmod 600 "$PASSWORD_FILE"
    gosu postgres "$INITDB_BIN" -D "$PGDATA" --username="$POSTGRES_USER" --pwfile="$PASSWORD_FILE" >/dev/null
    rm -f "$PASSWORD_FILE"
    trap - EXIT
  fi

  gosu postgres "$PG_CTL_BIN" \
    -D "$PGDATA" \
    -l /var/log/postgresql/postgresql.log \
    -o "-c listen_addresses=127.0.0.1 -p $POSTGRES_PORT" \
    -w start

  POSTGRES_STARTED=1

  if ! gosu postgres "$PSQL_BIN" -tAc "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'" postgres | grep -q 1; then
    gosu postgres "$CREATEDB_BIN" -O "$POSTGRES_USER" "$POSTGRES_DB"
  fi
}

start_local_redis() {
  mkdir -p /data

  if [ -n "$REDIS_PASSWORD" ]; then
    redis-server \
      --bind 127.0.0.1 \
      --port "$REDIS_PORT" \
      --dir /data \
      --daemonize yes \
      --requirepass "$REDIS_PASSWORD"
  else
    redis-server \
      --bind 127.0.0.1 \
      --port "$REDIS_PORT" \
      --dir /data \
      --daemonize yes
  fi

  REDIS_STARTED=1
}

cleanup() {
  if [ "$POSTGRES_STARTED" -eq 1 ]; then
    gosu postgres "$PG_CTL_BIN" -D "$PGDATA" -m fast stop >/dev/null 2>&1 || true
  fi

  if [ "$REDIS_STARTED" -eq 1 ]; then
    if [ -n "$REDIS_PASSWORD" ]; then
      redis-cli -h 127.0.0.1 -p "$REDIS_PORT" -a "$REDIS_PASSWORD" shutdown >/dev/null 2>&1 || true
    else
      redis-cli -h 127.0.0.1 -p "$REDIS_PORT" shutdown >/dev/null 2>&1 || true
    fi
  fi
}

if [ -z "${DATABASE_URL:-}" ]; then
  export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
fi

if [ -z "${REDIS_URL:-}" ]; then
  if [ -n "$REDIS_PASSWORD" ]; then
    export REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"
  else
    export REDIS_URL="redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"
  fi
fi

if is_local_host "$POSTGRES_HOST"; then
  start_local_postgres
fi

if is_local_host "$REDIS_HOST"; then
  start_local_redis
fi

wait_for_postgres
wait_for_redis

APP_MODE="${APP_MODE:-all}"
WEB_PORT="${PORT:-8000}"

trap cleanup EXIT INT TERM

BOT_PID=""
WEB_PID=""

if [ "$APP_MODE" = "web" ] || [ "$APP_MODE" = "all" ]; then
  python -m uvicorn src.web.app:app --host 0.0.0.0 --port "$WEB_PORT" &
  WEB_PID=$!
fi

if [ "$APP_MODE" = "bot" ] || [ "$APP_MODE" = "all" ]; then
  python -m src.bot.main &
  BOT_PID=$!
fi

if [ -n "$WEB_PID" ] && [ -n "$BOT_PID" ]; then
  wait "$WEB_PID" "$BOT_PID"
elif [ -n "$WEB_PID" ]; then
  wait "$WEB_PID"
elif [ -n "$BOT_PID" ]; then
  wait "$BOT_PID"
else
  echo "Nothing to run: APP_MODE must be one of bot, web, all" >&2
  exit 1
fi
