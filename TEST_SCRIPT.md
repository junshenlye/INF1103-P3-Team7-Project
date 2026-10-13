# Stackplan test script

This is the teacher-facing procedure for verifying Stackplan. The automated
runner explains each test group before executing it, displays every result, and
saves the complete console output under `test-results/`.

## Prerequisites

- Docker Desktop with Linux containers and Docker Compose 2.24 or newer
- Python 3.12 with the packages in `requirements-dev.txt`
- Node.js with `npm`

Install the Python development packages once if they are not already present:

```text
python -m pip install -r requirements-dev.txt
```

The normal automated tests use fake AI responses and do not require a
DashScope key or consume API credits.

## Run every automated test

On Windows PowerShell, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\run.ps1
```

On macOS or Linux, run:

```sh
sh ./tests/run.sh
```

Both commands run all four required groups:

| Group | What it verifies |
| --- | --- |
| Manager and business rules | Input validation, AI-response parsing, assessment normalization, Week 7 recess rules, weights, scheduling, recommendations, and data behaviour |
| Frontend contracts | Upload forwarding, partial errors, safe rendering, unknown dates, weight labels, capacity, and plan selection |
| Docker workflow | API flow, the complete manager pipeline, Docker file staging, and PostgreSQL persistence using an isolated disposable database |
| Deployment smoke test | A real database/API/frontend startup, health checks, homepage delivery, and a database write/read round trip through the frontend proxy |

The log lists every automated test by name with its `PASSED`, `SKIPPED`, or
failure result. The final console heading must say
`AUTOMATED TEST RESULT - PASS`. A failure returns a nonzero exit code and
identifies the failed command. Every run writes a timestamped file such as
`test-results/stackplan-tests-20261013-220000.log`.

A successful run also ends with a `✅` verification checklist summarising the
specific behaviours that were tested. The actual UI run remains marked `⬜`
until the teacher completes the manual procedure below.

An individual group may be selected by supplying `function`, `frontend`,
`workflow`, or `deployment`. For example:

```powershell
.\tests\run.ps1 -Group deployment
```

```sh
sh ./tests/run.sh deployment
```

## Required actual run through the UI

After the automated tests pass, run the real application through its user
interface. This test uses the live Qwen service and therefore requires a valid
`DASHSCOPE_API_KEY` in `.env`. Never include that key in the submission ZIP.

Start Stackplan on Windows:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local_windows.ps1
```

Start Stackplan on macOS or Linux:

```sh
./scripts/run_local_unix.sh
```

Then open <http://127.0.0.1:5173> and perform this acceptance test:

1. Enter a trimester name.
2. Add four modules named `HSC1007`, `HSC1009`, `HSC1010`, and `OTY1103`.
3. Keep or enter the appropriate credit value for each module.
4. Upload the matching files from `tests/fixtures/live/images/`.
5. Select **Build assessment schedule** and allow several minutes for the live
   AI processing to finish.
6. Confirm that all four modules appear in the Week 1–14 schedule.
7. Open each module and check its assessment names, weeks, and weights against
   the source image.
8. Open the study plan and confirm that it refers to scheduled assessments.
9. Reload the page and reopen the saved trimester to confirm persistence.

The expected source facts are:

| Module | Expected assessment timing and weights |
| --- | --- |
| HSC1007 | Week 8 at 30%; two Week 13 assessments at 35% each |
| HSC1009 | Week 5 at 35%; quizzes across Weeks 2, 4, and 6 at 30% total; Week 8 at 35% |
| HSC1010 | Week 8 at 40%; Week 10 at 30%; Week 14 at 30% |
| OTY1103 | Week 6 at 35%; Week 9 at 35%; Week 12 at 30% |

Week 7 should remain recess because none of these source images explicitly
schedules an assessment in Week 7.

## Optional live command-line check

With a valid key configured, the following command sends the HSC1010 fixture
through the real AI pipeline and consumes API credits:

```powershell
.\tests\run.ps1 -Group live
```

```sh
sh ./tests/run.sh live
```
