#!/usr/bin/env sh

# Teacher-facing Stackplan test runner for macOS and Linux.
set -eu

script_directory="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(dirname "$script_directory")"
script_path="$script_directory/run.sh"

# Re-run once through tee so every command and result is shown on screen and
# retained in a timestamped log. A status file preserves the test exit code
# without depending on non-portable shell pipefail behaviour.
if [ "${STACKPLAN_TEST_LOGGING:-0}" != "1" ]; then
    log_directory="$repository_root/test-results"
    mkdir -p "$log_directory"
    timestamp="$(date '+%Y%m%d-%H%M%S')"
    log_file="$log_directory/stackplan-tests-$timestamp.log"
    status_file="$(mktemp "${TMPDIR:-/tmp}/stackplan-tests.XXXXXX")"

    (
        set +e
        STACKPLAN_TEST_LOGGING=1 STACKPLAN_TEST_LOG_FILE="$log_file" \
            sh "$script_path" "$@"
        test_status=$?
        printf '%s\n' "$test_status" > "$status_file"
        exit 0
    ) 2>&1 | tee "$log_file"

    test_status=1
    if [ -s "$status_file" ]; then
        test_status="$(cat "$status_file")"
    fi
    rm -f "$status_file"

    if [ "$test_status" -ne 0 ]; then
        {
            printf '\n============================================================\n'
            printf 'AUTOMATED TEST RESULT — FAIL\n'
            printf '============================================================\n'
            printf 'Review the failure above and the full log: %s\n' "$log_file"
        } | tee -a "$log_file"
    else
        printf 'Test log saved to: %s\n' "$log_file" | tee -a "$log_file"
    fi
    exit "$test_status"
fi

cd "$repository_root"

python_command="${STACKPLAN_PYTHON:-}"
# Verbose output lists every test name and its PASS/SKIP result in the log.
pytest_output="${STACKPLAN_PYTEST_OUTPUT:--v}"
function_tests_passed=false
frontend_tests_passed=false
workflow_tests_passed=false
deployment_tests_passed=false
live_test_passed=false
if [ -z "$python_command" ]; then
    if [ -x .venv/bin/python ]; then
        python_command=.venv/bin/python
    else
        python_command=python3
    fi
fi

heading() {
    printf '\n============================================================\n'
    printf '%s\n' "$1"
    printf '============================================================\n'
}

describe() {
    printf '%s\n' "$1"
    printf 'Command: %s\n\n' "$2"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        printf 'Required command not found: %s\n' "$1" >&2
        exit 1
    }
}

check_python() {
    if ! "$python_command" --version >/dev/null 2>&1; then
        printf 'Python is unavailable. Install Python 3.12 and requirements-dev.txt.\n' >&2
        exit 1
    fi
}

check_docker() {
    require_command docker
    if ! docker compose version >/dev/null 2>&1; then
        printf 'Docker Compose 2.24 or newer is required.\n' >&2
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        printf 'Docker is installed but is not running. Start Docker and retry.\n' >&2
        exit 1
    fi
}

run_function_tests() {
    heading "TEST GROUP 1 — Manager and business-rule tests"
    describe \
        "Checks image intake, AI response parsing, schedule construction, Week 7 recess rules, assessment weights, recommendations, and data-manager behaviour. AI calls are mocked, so this group does not use API credits." \
        "$python_command -m pytest tests/function"
    PYTHONPATH=. "$python_command" -m pytest "$pytest_output" \
        -p no:cacheprovider tests/function
    function_tests_passed=true
    printf 'PASS — Manager and business-rule tests completed.\n'
}

run_frontend_tests() {
    heading "TEST GROUP 2 — Frontend contract and browser-logic tests"
    describe \
        "Checks upload forwarding, partial-error display, safe HTML rendering, assessment weight labels, unknown dates, schedule capacity, and study-plan selection." \
        "$python_command -m pytest tests/frontend/test_frontend.py; npm run check --prefix frontend"
    PYTHONPATH=. "$python_command" -m pytest "$pytest_output" \
        -p no:cacheprovider tests/frontend/test_frontend.py
    npm run check --prefix frontend
    frontend_tests_passed=true
    printf 'PASS — Frontend contract and browser-logic tests completed.\n'
}

clean_workflow_services() {
    docker compose --project-name "$test_project" --profile test \
        down --volumes >/dev/null 2>&1 || true
}

run_workflow_tests() {
    heading "TEST GROUP 3 — Docker workflow and PostgreSQL tests"
    describe \
        "Builds the test container and checks the API workflow, complete manager pipeline, Docker file staging, and real PostgreSQL persistence in an isolated disposable database." \
        "docker compose --profile test run tests"
    test_project=stackplan-workflow-tests
    trap clean_workflow_services EXIT INT TERM
    docker compose --project-name "$test_project" --profile test \
        run --build --rm --no-TTY tests \
        "$pytest_output" -p no:cacheprovider \
        tests/workflow tests/function/test_data_manager.py
    clean_workflow_services
    trap - EXIT INT TERM
    workflow_tests_passed=true
    printf 'PASS — Docker workflow and PostgreSQL tests completed.\n'
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

run_deployment_checks() {
    heading "TEST GROUP 4 — Full deployment smoke test"
    describe \
        "Builds and starts the real database, API, and frontend. It checks both health endpoints, loads the homepage, and verifies a project can be written through the frontend proxy and read back from PostgreSQL." \
        "docker compose up database api frontend; python tests/deployment/smoke.py"
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
    deployment_tests_passed=true
    printf 'PASS — Full deployment smoke test completed.\n'
}

run_live_cli_test() {
    heading "OPTIONAL LIVE AI TEST — One real module image"
    describe \
        "Processes the HSC1010 fixture through the real Qwen service. This requires DASHSCOPE_API_KEY in .env, consumes API credits, and is intentionally excluded from the automated all mode." \
        "docker compose run --rm stackplan-cli /input/tests/fixtures/live/one-module.json"
    docker compose run --rm stackplan-cli \
        /input/tests/fixtures/live/one-module.json
    live_test_passed=true
    printf 'PASS — Optional live AI CLI test completed.\n'
}

print_verification_summary() {
    heading "FINAL VERIFICATION SUMMARY"

    if [ "$function_tests_passed" = true ]; then
        printf '%s\n' \
            "✅ Image intake, validation, and multi-image module handling" \
            "✅ AI response parsing, relevance checks, and failure handling" \
            "✅ Assessment normalization, weights, ranking, and module ownership" \
            "✅ Week 1–14 scheduling, unknown dates, and Week 7 recess rules" \
            "✅ Study-plan recommendations and workload limits"
    fi

    if [ "$frontend_tests_passed" = true ]; then
        printf '%s\n' \
            "✅ Frontend upload forwarding and multipart file handling" \
            "✅ Partial errors, unknown dates, weights, and plan display" \
            "✅ Safe rendering of untrusted source text"
    fi

    if [ "$workflow_tests_passed" = true ]; then
        printf '%s\n' \
            "✅ Complete API and manager workflow in Docker" \
            "✅ PostgreSQL save, reload, and latest-result persistence" \
            "✅ Isolated test database cleanup"
    fi

    if [ "$deployment_tests_passed" = true ]; then
        printf '%s\n' \
            "✅ Production database, API, and frontend containers started healthy" \
            "✅ Frontend homepage and proxy were reachable" \
            "✅ Project write/read round trip through PostgreSQL"
    fi

    if [ "$live_test_passed" = true ]; then
        printf '✅ Live HSC1010 image processed through the configured Qwen service\n'
    fi

    printf '⬜ Manual UI run still required — follow the steps below\n'
}

print_ui_instructions() {
    heading "REQUIRED MANUAL CHECK — Run Stackplan through the actual UI"
    printf '%s\n' \
        "Automated tests cannot replace a real user run. Add DASHSCOPE_API_KEY to .env, then start the application:" \
        "" \
        "  macOS/Linux: ./scripts/run_local_unix.sh" \
        "  Windows:     powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\run_local_windows.ps1" \
        "" \
        "Open http://127.0.0.1:5173 and create a trimester." \
        "Add HSC1007, HSC1009, HSC1010, and OTY1103 as four modules." \
        "Upload the matching JPEG files from tests/fixtures/live/images/." \
        "Confirm that the Week 1–14 schedule, assessment details, and study plan appear, and that the saved trimester can be reopened." \
        "" \
        "Do not submit an API key in the project ZIP."
}

requested_group="${1:-all}"

heading "STACKPLAN TEACHER TEST SCRIPT"
printf 'Selected test group: %s\n' "$requested_group"
printf 'Repository: %s\n' "$repository_root"
printf 'Full log: %s\n' "${STACKPLAN_TEST_LOG_FILE:-not configured}"

case "$requested_group" in
    function)
        check_python
        run_function_tests
        ;;
    frontend)
        check_python
        require_command npm
        run_frontend_tests
        ;;
    workflow)
        check_docker
        run_workflow_tests
        ;;
    deployment)
        check_python
        check_docker
        run_deployment_checks
        ;;
    live)
        check_docker
        run_live_cli_test
        ;;
    all)
        check_python
        require_command npm
        check_docker
        run_function_tests
        run_frontend_tests
        run_workflow_tests
        run_deployment_checks
        ;;
    *)
        printf 'Usage: %s {all|function|frontend|workflow|deployment|live}\n' "$0" >&2
        exit 2
        ;;
esac

heading "AUTOMATED TEST RESULT — PASS"
printf 'The selected Stackplan test group completed successfully.\n'
print_verification_summary
print_ui_instructions
