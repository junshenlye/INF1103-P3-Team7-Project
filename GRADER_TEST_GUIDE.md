# Grader test guide

Install Python 3.12, Node.js 22+ and Docker Desktop with Linux containers, then:

```sh
python -m pip install -r requirements-dev.txt
sh tests/run.sh full
```

Windows PowerShell: `.\tests\run.ps1 -Group full`. For frequent offline feedback,
select `fast`. A successful full run ends with `FULL PASS`; required integration
checks cannot skip. Logs, JUnit, coverage and summaries are in `test-results/`.
See [tests/README.md](tests/README.md) for isolation and troubleshooting.

Automated tests need no DashScope key and consume no AI credits. They exercise
both Python and JavaScript in Docker, real disposable PostgreSQL, and the built
frontend/API containers. They do not verify live Qwen quality.

For an optional live UI assessment, configure `.env` as documented in the README,
start `scripts/run_local_unix.sh` (Windows: `scripts/run_local_windows.ps1`) and
open <http://127.0.0.1:5173>. Create a trimester and upload the matching HSC1007,
HSC1009, HSC1010 and OTY1103 images from `grader-test-case/images/`. Confirm the
schedule and advice appear, then reopen the saved trimester. This consumes
Qwen credits; keep credentials out of the submitted project.
