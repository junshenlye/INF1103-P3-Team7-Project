#!/usr/bin/env sh

# Run one clearly scoped Stackplan test group.
set -eu

cd "$(dirname "$0")/.."

python_command="${STACKPLAN_PYTHON:-}"
if [ -z "$python_command" ]; then
    if [ -x .venv/bin/python ]; then
        python_command=.venv/bin/python
    else
        python_command=python3
    fi
fi

run_function_tests() {
    PYTHONPATH=. "$python_command" -m pytest -q -p no:cacheprovider tests/function
}

run_frontend_tests() {
    PYTHONPATH=. "$python_command" -m pytest -q -p no:cacheprovider \
        tests/frontend/test_frontend.py
    npm run check --prefix frontend
}

clean_workflow_services() {
    docker compose --project-name "$test_project" --profile test \
        down --volumes >/dev/null 2>&1 || true
}

run_workflow_tests() {
    test_project=stackplan-workflow-tests
    trap clean_workflow_services EXIT INT TERM
    docker compose --project-name "$test_project" --profile test \
        run --build --rm --no-TTY tests \
        -q -p no:cacheprovider \
        tests/workflow tests/function/test_data_manager.py
    clean_workflow_services
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
        echo "Usage: $0 {function|frontend|workflow|live|all}" >&2
        exit 2
        ;;
esac
