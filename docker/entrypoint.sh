#!/bin/sh
set -eu

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-telegram_task_checker}"
POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_DB="${REDIS_DB:-0}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

export POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB POSTGRES_HOST POSTGRES_PORT
export REDIS_HOST REDIS_PORT REDIS_DB REDIS_PASSWORD

export DATABASE_URL="${DATABASE_URL:-postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB}"

if [ -n "$REDIS_PASSWORD" ]; then
  export REDIS_URL="${REDIS_URL:-redis://:$REDIS_PASSWORD@$REDIS_HOST:$REDIS_PORT/$REDIS_DB}"
else
  export REDIS_URL="${REDIS_URL:-redis://$REDIS_HOST:$REDIS_PORT/$REDIS_DB}"
fi

POSTGRES_DATA_DIR="/var/lib/postgresql/data"
POSTGRES_SOCKET_DIR="/var/run/postgresql"
POSTGRES_LOG_FILE="/var/log/postgresql/postgres.log"
REDIS_DATA_DIR="/data"
REDIS_CONF_FILE="/tmp/redis.conf"
POSTGRES_BIN_DIR="$(find /usr/lib/postgresql -mindepth 2 -maxdepth 2 -type d -name bin | sort | tail -n 1)"

if [ -z "$POSTGRES_BIN_DIR" ]; then
  echo "PostgreSQL binaries directory not found" >&2
  exit 1
fi

INITDB_BIN="$POSTGRES_BIN_DIR/initdb"
PG_CTL_BIN="$POSTGRES_BIN_DIR/pg_ctl"
PG_ISREADY_BIN="$POSTGRES_BIN_DIR/pg_isready"
PSQL_BIN="$POSTGRES_BIN_DIR/psql"
CREATEDB_BIN="$POSTGRES_BIN_DIR/createdb"

mkdir -p "$POSTGRES_DATA_DIR" "$POSTGRES_SOCKET_DIR" "$(dirname "$POSTGRES_LOG_FILE")" "$REDIS_DATA_DIR"
chown -R postgres:postgres /var/lib/postgresql /var/run/postgresql /var/log/postgresql
chmod 700 "$POSTGRES_DATA_DIR"

if [ ! -s "$POSTGRES_DATA_DIR/PG_VERSION" ]; then
  su postgres -c "'$INITDB_BIN' -D '$POSTGRES_DATA_DIR'"
fi

POSTGRES_CONF="$POSTGRES_DATA_DIR/postgresql.conf"
PG_HBA_CONF="$POSTGRES_DATA_DIR/pg_hba.conf"

if grep -q "^#\?listen_addresses" "$POSTGRES_CONF"; then
  sed -i "s/^#\?listen_addresses.*/listen_addresses = '*'/" "$POSTGRES_CONF"
else
  echo "listen_addresses = '*'" >> "$POSTGRES_CONF"
fi

if ! grep -q "^host all all all scram-sha-256$" "$PG_HBA_CONF"; then
  echo "host all all all scram-sha-256" >> "$PG_HBA_CONF"
fi

su postgres -c "'$PG_CTL_BIN' -D '$POSTGRES_DATA_DIR' -l '$POSTGRES_LOG_FILE' -o '-p $POSTGRES_PORT' start"

until "$PG_ISREADY_BIN" -h 127.0.0.1 -p "$POSTGRES_PORT" -U postgres >/dev/null 2>&1; do
  sleep 1
done

su postgres -c "'$PSQL_BIN' -v ON_ERROR_STOP=1 --username postgres --dbname postgres -c \"ALTER USER postgres WITH PASSWORD '$POSTGRES_PASSWORD';\""

if ! su postgres -c "'$PSQL_BIN' -tAc \"SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'\" postgres" | grep -q 1; then
  su postgres -c "'$CREATEDB_BIN' -O postgres '$POSTGRES_DB'"
fi

cat > "$REDIS_CONF_FILE" <<EOF
bind 127.0.0.1
port $REDIS_PORT
dir $REDIS_DATA_DIR
daemonize yes
save 60 1
appendonly yes
EOF

if [ -n "$REDIS_PASSWORD" ]; then
  echo "requirepass $REDIS_PASSWORD" >> "$REDIS_CONF_FILE"
fi

redis-server "$REDIS_CONF_FILE"

if [ -n "$REDIS_PASSWORD" ]; then
  until redis-cli -h 127.0.0.1 -p "$REDIS_PORT" -a "$REDIS_PASSWORD" ping >/dev/null 2>&1; do
    sleep 1
  done
else
  until redis-cli -h 127.0.0.1 -p "$REDIS_PORT" ping >/dev/null 2>&1; do
    sleep 1
  done
fi

cleanup() {
  if [ -n "${BOT_PID:-}" ] && kill -0 "$BOT_PID" >/dev/null 2>&1; then
    kill "$BOT_PID" >/dev/null 2>&1 || true
    wait "$BOT_PID" 2>/dev/null || true
  fi

  redis-cli -h 127.0.0.1 -p "$REDIS_PORT" ${REDIS_PASSWORD:+-a "$REDIS_PASSWORD"} shutdown >/dev/null 2>&1 || true
  su postgres -c "'$PG_CTL_BIN' -D '$POSTGRES_DATA_DIR' -m fast stop" >/dev/null 2>&1 || true
}

trap cleanup INT TERM EXIT

python -m src.bot.main &
BOT_PID=$!

wait "$BOT_PID"