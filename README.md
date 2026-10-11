# Stackplan

Stackplan extracts assessment information from module screenshots, builds a
Week 1-14 schedule, stores revision history in PostgreSQL, and can generate a
validated work checklist or trimester revision plan.

The submission keeps the core procedure in `src/`:

```text
IO Manager -> AI Manager -> Logic Manager -> Data Manager
```

HTTP, Docker staging and HTML rendering are adapters under `helpers/`. A future
frontend is intentionally separate from the Python submission.

## Requirements

- Docker with Docker Compose
- A DashScope API key for live Qwen processing
- Python 3.12 for non-Docker development

Create the environment file:

```sh
cp .env.example .env
```

Add `DASHSCOPE_API_KEY` to `.env`. Database defaults are suitable for local
Compose development and can be changed in the same file.

## Run with Docker

Build the application and start PostgreSQL:

```sh
docker compose build
docker compose up --detach database
```

Run the one-module low-cost payload:

```sh
docker compose run --rm stackplan-cli /input/test_payload_quick.json
```

Run all supplied module examples:

```sh
docker compose run --rm stackplan-cli /input/test_payload.json
```

Compose waits for PostgreSQL's health check before starting the CLI. The
database schema is created from `database/schema.sql` when the database volume
is created for the first time.

## Docker payload helper

The helper accepts a payload anywhere on the host, stages its referenced images
in a temporary directory, starts PostgreSQL and invokes the Compose CLI:

```sh
python -m helpers.docker_cli test_payload_quick.json \
  --project-name "Trimester 1" \
  --output stackplan-result.json
```

The temporary intake directory is removed after the command. Credentials stay
in `.env` and are not added to the command line or Docker image.

## Run locally

PostgreSQL can remain in Docker while the Python program runs locally:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
docker compose up --detach database
```

Use a host-accessible database URL before running the CLI. The Compose database
does not publish a host port by default, so direct local Python runs may omit
`DATABASE_URL`; processing still works but persistence is skipped. Docker is
the recommended complete workflow.

```sh
python -m src.main test_payload_quick.json
```

The CLI prints one JSON document containing `payload` and `errors`. Logs use
standard error, so redirected JSON remains valid. Complete pipeline failure
returns a non-zero process status.

## API helper

Start PostgreSQL and the frontend-facing helper:

```sh
docker compose up --build api
```

The API listens on `http://localhost:8000`. Important endpoints are:

```text
GET    /health
GET    /api/projects
POST   /api/projects
GET    /api/projects/{project_id}
POST   /api/projects/{project_id}/process
GET    /api/projects/{project_id}/schedule
PUT    /api/projects/{project_id}/modules/{module_title}
POST   /api/projects/{project_id}/modules/{module_title}/confirm
GET    /api/projects/{project_id}/recommendations
POST   /api/projects/{project_id}/recommendations
POST   /api/projects/{project_id}/recommendations/{id}/status
```

The API contains no assessment business logic. It invokes the core CLI or calls
the public manager interfaces and returns JSON for the future frontend.

## AI recommendations

AI Manager supports two recommendation types:

- `work_checklist`
- `trimester_revision_plan`

Recommendations use confirmed module records only. Local validation rejects
unknown assessment IDs, unknown modules, invalid teaching weeks, mismatched
week groups and plans exceeding the student's stated weekly hours. Advice is
stored separately and never changes assessment weights, weeks or names.

Example recommendation request body:

```json
{
  "recommendation_type": "work_checklist",
  "preferences": {
    "available_hours_per_week": 8,
    "current_week": 4,
    "preferred_days": ["Tuesday", "Saturday"]
  }
}
```

## Data storage

PostgreSQL stores:

- trimester projects;
- pipeline runs and hard errors;
- versioned normalized module JSON;
- confirmed and candidate module revisions;
- recommendation candidates and their acceptance state.

The first extraction of a module is confirmed automatically. A later AI rerun
is stored as a candidate and cannot overwrite confirmed student data. Manual
edits create another revision so the original extraction remains auditable.

The source hash, prompt version and model combination form an extraction cache.
An identical complete rerun can reuse confirmed module results and avoid Qwen
requests.

## Tests

Tests are divided by intent:

```text
tests/function/  - manager functions and deterministic validation
tests/workflow/  - manager chain, database, API and Docker staging
```

Run tests that do not require PostgreSQL:

```sh
source .venv/bin/activate
PYTHONPATH=. pytest -q -p no:cacheprovider
```

Run the complete suite against a disposable PostgreSQL container:

```sh
docker compose -f compose.test.yaml up \
  --build \
  --abort-on-container-exit \
  --exit-code-from tests
```

The test database uses temporary container storage and does not touch the
development volume. Tests use fake AI responses and do not consume Qwen tokens.
The explicit quick-test script is the opt-in live model check:

```sh
./scripts/run_quick_test.sh
```

## Timetable snapshot helper

The old HTML view remains a presentation adapter and is not part of `src`:

```sh
python -m helpers.timetable_renderer \
  stackplan-result.json \
  frontend-demo/timetable.html
```

The future frontend should consume API data rather than this generated file.
See [system design](docs/system-design.md) and the
[Astra frontend design sheet](docs/astra-frontend-design-sheet.md).
