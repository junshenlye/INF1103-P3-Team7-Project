#!/usr/bin/env sh

# Start PostgreSQL, the helper API and the frontend on macOS or Linux.
set -eu

operating_system="$(uname -s)"
case "$operating_system" in
    Darwin|Linux)
        ;;
    *)
        echo "This launcher is for macOS and Linux. Use the Windows PowerShell launcher on Windows." >&2
        exit 1
        ;;
esac

cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker with Docker Compose is required to start Stackplan." >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose 2.24 or newer is required to start Stackplan." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running. Start it and try again." >&2
    exit 1
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example. Add DASHSCOPE_API_KEY before using AI features." >&2
fi

# Create the bind-mount parent as the current user. PostgreSQL creates and owns
# its pgdata subdirectory, avoiding host-permission differences across machines.
mkdir -p database/data

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
