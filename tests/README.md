# Test strategy

For the complete teacher-facing procedure, Windows and macOS/Linux commands,
timestamped logs, and the required manual UI run, see
[`TEST_SCRIPT.md`](../TEST_SCRIPT.md).

Stackplan tests observable outcomes, manager boundaries and previously found
bugs. Normal automated tests never call the live Qwen API or consume tokens.

## Test groups

| Group | Question it answers | macOS/Linux command | Windows command |
| --- | --- | --- | --- |
| Manager outcomes | Do intake, AI parsing, scheduling and recommendation rules make the correct decision? | `sh ./tests/run.sh function` | `.\tests\run.ps1 -Group function` |
| Frontend contracts | Does the UI preserve uploads, partial errors, unknown dates and backend response meaning? | `sh ./tests/run.sh frontend` | `.\tests\run.ps1 -Group frontend` |
| Docker workflow | Do the API, complete pipeline and PostgreSQL persistence work together in containers? | `sh ./tests/run.sh workflow` | `.\tests\run.ps1 -Group workflow` |
| Deployment smoke | Can a clean machine build the real stack, reach both services and complete a database-backed request through the frontend? | `sh ./tests/run.sh deployment` | `.\tests\run.ps1 -Group deployment` |

Running either script without a group runs all four automated groups and saves
the complete output in `test-results/`.

The Docker workflow uses an isolated temporary database. It cannot modify the
development data stored in `database/data/`.

GitHub Actions runs only the deployment smoke check. The detailed regression
groups remain available to developers and should be run when their area changes.

## Regression cases

These tests came from concrete failures or high-risk requirements:

| Risk or previous bug | Protected outcome |
| --- | --- |
| An INF1103 image populated INF1102 | Visible and requested module codes must agree; uploaded files stay attached to their submitted module. |
| “Tutorials x10 - 5%” became ten items worth 5% each | Repeated items may expand for scheduling, but the 5% remains one group total. |
| Work appeared during Week 7 recess | Recurring or ranged work skips recess unless the source explicitly states Week 7. |
| An assessment with no date became Week 1 advice | Unknown dates stay outside numbered schedule and study-plan weeks. |
| One failed image discarded usable modules | Hard errors are retained while valid modules and soft comments continue. |
| A rerun displayed stale module data | PostgreSQL returns the newest complete saved pipeline result. |
| The frontend hid partial API failures | Usable payloads and their warnings are displayed together. |

## Adding a test

Add a test when a business rule is introduced or a real bug is fixed. Name it
after the outcome, reproduce the smallest meaningful input, and assert the
public result or error. Avoid tests that only duplicate implementation details.
