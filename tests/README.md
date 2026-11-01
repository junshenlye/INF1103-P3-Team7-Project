# Verification

From the repository root, install `requirements-dev.txt` in `.venv` and use
Python 3.12, Node.js 22+ and Docker with Compose 2.24+. Python 3.9 is also
exercised locally; containers and CI use 3.12. No Qwen credentials are required.

| Mode | macOS / Linux | Windows PowerShell | Required checks |
| --- | --- | --- | --- |
| Fast | `sh tests/run.sh fast` | `.\tests\run.ps1 -Group fast` | Ruff, offline Python, JS syntax and contracts |
| Full | `sh tests/run.sh full` | `.\tests\run.ps1 -Group full` | Fast, all Python/JS tests in Docker, real PostgreSQL, application smoke |

`python tests/verify.py MODE` is the shared implementation. Default mode is
`full`; `all` and `workflow` remain shell/PowerShell aliases for `full` and
`integration`. CI invokes `fast`, `integration`, then `deployment`, in order.
`STACKPLAN_PYTHON` selects an alternative interpreter for either wrapper.
Focused development runs can use `python -m pytest -m 'not integration' PATH`
and `npm run check --prefix frontend`.

## Behaviour and contracts

- Domain tests cover identities, immutable nested state, timing, recurrence,
  uncertainty, group weights and ranking before schedule appearances are copied.
- Generator contracts run both existing implementations through the same async
  inputs and failure cases; a registration case verifies workflow extension.
- Application tests fake the provider, run all other planning layers, and cover
  complete/partial/failed outcomes, concurrency, timeout, cleanup and storage loss.
- Repository contracts run the same cases against memory and PostgreSQL:
  legacy JSON preservation, newest usable result, atomic rollback and advice status.
- HTTP tests cover uploads, partial results, consistent error JSON and a complete
  processing/advice/reload path against PostgreSQL. Frontend Python proxy and JS
  tests preserve partial errors, safe rendering, unknown dates and capacity.
- Smoke tests build the actual API/frontend images, require readiness, load the
  homepage, and write/read a project through the frontend proxy and PostgreSQL.

## Isolation and failures

Fast mode explicitly deselects database cases. Required database checks never
skip when PostgreSQL is unavailable; container mode fails if any test skips.
The destructive fixture requires `STACKPLAN_TEST_DATABASE=1`, user/database
`stackplan_test`, and a local or Compose test host. Do not point it at development
data. Tests prohibit creating a real Qwen SDK client or loading `.env`.

The standalone `tests/deployment/compose.yaml` uses a random Compose project,
a temporary PostgreSQL filesystem and no published ports, credentials or
`database/data/` mount. The gate cleans resources after success, failure or
interruption. Development Compose remains separate. A full gate needs Docker;
a missing daemon, failed build or failed readiness check is a failure.

## Reports and coverage

`test-results/` contains stage logs, `*-summary.json`, Python and JS JUnit reports,
and statement/branch coverage in XML/JSON. Logs and reports are ignored by Git.
CI uploads these even after failures. Read the failing stage's log first;
`*-docker.log` records service diagnostics. A gate timeout terminates its command
and runs resource cleanup.

The first instrumented refactor baseline was 74% offline and 79% in Docker.
After adding behavioural tests, floors are 75% offline and 80% with PostgreSQL
(statements and branches combined). Refactored domain/application/IO/AI/logic
packages each require 80%; storage requires 75% in Docker. Component floors
exclude transitional `__init__` adapters; the overall floor includes them.
Coverage guides investigation; assertions must protect behaviour, not just lines.

Live extraction and the optional manual browser run described in the grader
guide consume credits and are excluded from every automated mode.
