# Stackplan

Stackplan turns module assessment screenshots into a clear Week 1–14 workload
overview and an AI-generated study plan. It is a school project demonstrating a
complete DevOps workflow: multimodal extraction, deterministic scheduling,
PostgreSQL storage, a small HTTP API, a responsive frontend, Docker deployment
and automated tests.

It is designed for students who receive assessment information across several
module screenshots and need one reliable trimester view. The core problem is
not simply displaying those screenshots: Stackplan uses AI to interpret vague
or inconsistent assessment wording, then applies local rules so uncertain
dates and weights are never presented as confirmed facts.

## Features

- Upload one or more assessment screenshots for each module.
- Use Qwen in separate interpretation and normalization passes.
- Preserve uncertain information as comments instead of inventing facts.
- Place validated assessments into a Week 1–14 timetable.
- Rank workload using module credits and known assessment weights.
- Automatically generate workload highlights and a trimester study plan after
  scheduling.
- Keep Week 7 clear as recess unless source evidence explicitly schedules an
  assessment there.
- Store projects, complete pipeline results, errors and recommendations in
  PostgreSQL.
- Continue with usable modules when another module cannot be processed.
- Run the complete application with Docker Compose.

## How it works

```text
Browser
  -> Flask frontend
  -> Helper API
  -> main.py orchestration
     -> IO Manager
     -> AI Manager: Qwen extraction
     -> Logic Manager: normalize and schedule
     -> AI Manager: Qwen study advice
     -> Logic Manager: validate advice
     -> Data Manager -> PostgreSQL
```

The managers in `src/` have one responsibility each:

- **IO Manager** validates module metadata and safely stages images.
- **AI Manager** owns Qwen prompts, HTTP requests and JSON response parsing.
- **Logic Manager** normalizes AI output, expands repeated assessments, builds
  the weekly ranking, and validates study advice against the schedule.
- **Data Manager** stores projects, complete pipeline results and recommendations.

`main.py` deliberately owns the sequence between these managers. PostgreSQL
stores its files in the project at `database/data/`. Compose mounts that folder
into the database container, so saved projects survive container replacement
and the persistence boundary is visible during assessment. The runtime files
are excluded from Git because PostgreSQL manages their binary format.

Hard failures are appended to the shared `errors` list. Unclear assessment
details remain attached to the affected module or schedule item as comment
metadata, so one vague screenshot does not discard the rest of the result.

## Assignment alignment

- The assessed Python pipeline is fully procedural; there are no class
  definitions.
- Every accepted module image passes through Qwen relevance, interpretation
  and normalization calls. Removing AI extraction removes the application's
  central ability to understand assessment screenshots.
- AI Manager parses JSON and checks the response container. Logic Manager then
  validates domain fields before scheduling or displaying them.
- Logic Manager contains the business rules. Its importance ranking combines
  an explicit module-level assessment weight with module credits, ranks all
  comparable assessments, and keeps group-only or unknown weights unranked.
- The permitted PostgreSQL persistence option stores complete JSON documents
  as JSONB while keeping database access behind Data Manager functions.
- Docker Compose provides the same services locally and in the test workflow.
- GitHub Actions builds and smoke-tests the complete Docker deployment on
  pushes and pull requests.

## Repository structure

```text
src/                 assessed manager pipeline
helpers/             HTTP API and Docker payload adapter
frontend/            independent Flask presentation layer
database/            PostgreSQL schema and ignored persistent runtime data
tests/function/      focused manager tests
tests/workflow/      pipeline, API and database workflow tests
tests/frontend/      frontend contract and browser checks
grader-test-case/    easy-to-find live JSON inputs and assessment images
scripts/run_local_unix.sh macOS and Linux local launcher
scripts/run_local_windows.ps1 Windows local launcher
compose.windows.yaml Windows-safe PostgreSQL storage override
compose.yaml         application and isolated test services
```

## Requirements

- Docker with Docker Compose 2.24 or newer
- PowerShell 5.1 or newer on Windows, with Docker Desktop using Linux containers
- A DashScope API key
- Python 3.12 for development outside Docker
- Node.js only for the optional frontend JavaScript checks

## Configure the environment

Create the local environment file on macOS or Linux (the launcher also does
this automatically when the file is missing):

```sh
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Open `.env` and set:

```text
DASHSCOPE_API_KEY=your-key
```

`DASHSCOPE_BASE_URL` and the local database values already have suitable
defaults. Compose reads `.env` automatically; credentials do not need to be
placed in a command or copied into an image.

## Run the complete project

Start the frontend, API and PostgreSQL database on macOS or Linux:

```sh
./scripts/run_local_unix.sh
```

On Windows, open PowerShell in the repository and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local_windows.ps1
```

The execution-policy override applies only to that PowerShell process; it does
not change the machine or user policy.

Open <http://127.0.0.1:5173>. Incoming browser and API requests are shown in
the terminal. Press `Ctrl+C` to stop the services; saved database data is kept.
The API and frontend do not poll one another. Their `/health` endpoints remain
available for an explicit diagnostic check without filling the logs.

On the first run, either launcher creates `.env` from `.env.example` when it is
missing, and PostgreSQL applies `database/schema.sql`. On macOS and Linux,
PostgreSQL files are kept in `database/data/`. Windows uses a Docker-managed
named volume because PostgreSQL data directories require Unix ownership and
permissions that Windows host folders do not reliably provide. Both storage
options survive container replacement.

To use a different frontend port:

```sh
FRONTEND_PORT=5174 ./scripts/run_local_unix.sh
```

On Windows PowerShell:

```powershell
$env:FRONTEND_PORT = "5174"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local_windows.ps1
```

## Run the pipeline from the command line

The small live example processes one module and consumes Qwen tokens:

```sh
sh ./tests/run.sh live
```

The supplied four-module example can be run with:

```sh
docker compose run --rm stackplan-cli \
  /input/grader-test-case/all-modules.json
```

To process a payload stored elsewhere, the adapter copies its referenced
images into a temporary Docker-readable directory:

```sh
python -m helpers.docker_cli path/to/payload.json \
  --project-name "Trimester 1" \
  --output stackplan-result.json
```

## Run with local Python

Create a development environment and install the project dependencies:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Run the manager pipeline directly:

```sh
python -m src.main grader-test-case/one-module.json
```

Direct execution reads `.env`. Without `DATABASE_URL`, the pipeline still
returns a result but skips PostgreSQL persistence. Docker Compose is the
recommended way to demonstrate the complete system.

## Run the tests

All test code and fixtures are contained in `tests/`. Normal tests use fake AI
responses and do not consume Qwen tokens. See the
[`GRADER_TEST_GUIDE.md`](GRADER_TEST_GUIDE.md) for the complete Windows,
macOS, Linux, and manual UI instructions.

Run every automated test on macOS or Linux:

```sh
sh ./tests/run.sh
```

Run every automated test on Windows PowerShell:

```powershell
.\tests\run.ps1
```

The runner prints a final verification summary and saves the full output in
`test-results/`.

## Inspect or export saved data

Start only PostgreSQL when the application services are not needed:

```sh
docker compose up --detach --wait database
```

Open PostgreSQL's command-line interface using the configured container
credentials:

```sh
docker compose exec database sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Useful commands inside that interface are `\dt` to list tables, `\d projects`
to inspect one table, and `\q` to exit. A desktop client such as pgAdmin,
DBeaver or TablePlus can also be added later by publishing PostgreSQL's port;
the default Compose setup keeps that port private to the application network.

Export a portable SQL backup without reading PostgreSQL's binary files:

```sh
docker compose exec database sh -c \
  'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > stackplan-backup.sql
```

The files below `database/data/` are the live database storage. PostgreSQL reads
and writes them through the bind mount; they should never be edited manually.
