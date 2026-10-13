#!/usr/bin/env sh

# Run one clearly scoped Stackplan test group.
set -eu

cd "$(dirname "$0")/.."

python_command="${STACKPLAN_PYTHON:-}"
pytest_output="${STACKPLAN_PYTEST_OUTPUT:--q}"
if [ -z "$python_command" ]; then
    if [ -x .venv/bin/python ]; then
        python_command=.venv/bin/python
    else
        python_command=python3
    fi
fi

run_function_tests() {
    PYTHONPATH=. "$python_command" -m pytest "$pytest_output" \
        -p no:cacheprovider tests/function
}

run_frontend_tests() {
    PYTHONPATH=. "$python_command" -m pytest "$pytest_output" \
        -p no:cacheprovider \
        tests/frontend/test_frontend.py
    npm run check --prefix frontend
}

clean_workflow_services() {
    docker compose --project-name "$test_project" --profile test \
        down --volumes >/dev/null 2>&1 || true
}

clean_deployment_services() {
    API_HOST_PORT="$deployment_api_port" \
    FRONTEND_PORT="$deployment_frontend_port" \
    docker compose --project-name "$deployment_project" \
        --file compose.yaml --file tests/deployment/compose.yaml \
        down --volumes >/dev/null 2>&1 || true
}

finish_deployment_checks() {
    exit_code=$?
    trap - EXIT INT TERM
    if [ "$exit_code" -ne 0 ]; then
        API_HOST_PORT="$deployment_api_port" \
        FRONTEND_PORT="$deployment_frontend_port" \
        docker compose --project-name "$deployment_project" \
            --file compose.yaml --file tests/deployment/compose.yaml \
            logs --no-color database api frontend || true
    fi
    clean_deployment_services
    exit "$exit_code"
}

run_workflow_tests() {
    test_project=stackplan-workflow-tests
    trap clean_workflow_services EXIT INT TERM
    docker compose --project-name "$test_project" --profile test \
        run --build --rm --no-TTY tests \
        "$pytest_output" -p no:cacheprovider \
        tests/workflow tests/function/test_data_manager.py
    clean_workflow_services
    trap - EXIT INT TERM
}

run_deployment_checks() {
    deployment_project=stackplan-deployment-check
    deployment_api_port="${STACKPLAN_DEPLOYMENT_API_PORT:-18000}"
    deployment_frontend_port="${STACKPLAN_DEPLOYMENT_FRONTEND_PORT:-15173}"
    trap finish_deployment_checks EXIT INT TERM

    API_HOST_PORT="$deployment_api_port" \
    FRONTEND_PORT="$deployment_frontend_port" \
    docker compose --project-name "$deployment_project" \
        --file compose.yaml --file tests/deployment/compose.yaml \
        config --quiet

    API_HOST_PORT="$deployment_api_port" \
    FRONTEND_PORT="$deployment_frontend_port" \
    docker compose --project-name "$deployment_project" \
        --file compose.yaml --file tests/deployment/compose.yaml \
        up --build --detach --wait database api frontend

    STACKPLAN_DEPLOYMENT_API_URL="http://127.0.0.1:$deployment_api_port" \
    STACKPLAN_DEPLOYMENT_FRONTEND_URL="http://127.0.0.1:$deployment_frontend_port" \
        "$python_command" tests/deployment/smoke.py

    clean_deployment_services
    trap - EXIT INT TERM
}

case "${1:-function}" in
    function)
        run_function_tests
        ;;
    frontend)
        run_frontend_tests
        ;;
    workflow)
        run_workflow_tests
        ;;
    deployment)
        run_deployment_checks
        ;;
    live)
        docker compose run --rm stackplan-cli \
            /input/tests/fixtures/live/one-module.json
        ;;
    all)
        run_function_tests
        run_frontend_tests
        run_workflow_tests
        ;;
    *)
        echo "Usage: $0 {function|frontend|workflow|deployment|live|all}" >&2
        exit 2
        ;;
esac
