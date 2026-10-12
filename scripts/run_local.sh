#!/usr/bin/env sh

# Start PostgreSQL, the helper API and the frontend together with Compose.
set -eu

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required to start Stackplan." >&2
    exit 1
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example. Add DASHSCOPE_API_KEY before using AI features." >&2
fi

stop_services() {
    exit_code=$?
    trap - EXIT INT TERM
    echo "Stopping Stackplan frontend, API and database..." >&2
    docker compose stop frontend api database >/dev/null 2>&1 || true
    exit "$exit_code"
}

trap stop_services EXIT INT TERM

frontend_port="${FRONTEND_PORT:-${PORT:-5173}}"
export FRONTEND_PORT="$frontend_port"

echo "Starting Stackplan at http://127.0.0.1:${frontend_port}" >&2
docker compose up --build --detach --wait frontend

echo "Stackplan is ready. Press Ctrl+C to stop it." >&2
docker compose logs --follow frontend api
