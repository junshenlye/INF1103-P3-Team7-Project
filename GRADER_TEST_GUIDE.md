# Grader test guide

## Requirements

- Docker Desktop running with Linux containers
- Python 3.12
- Node.js and npm

Install the Python test packages once:

```text
python -m pip install -r requirements-dev.txt
```

## Run all automated tests

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\run.ps1
```

macOS or Linux:

```sh
sh ./tests/run.sh
```

The runner explains each test group, lists each test result, and ends with a
`✅` summary. A successful run displays `AUTOMATED TEST RESULT - PASS`. The
complete output is saved in `test-results/`.

The automated tests do not require a DashScope API key or consume AI credits.

## Run the actual application through the UI

For the live UI run, add a valid `DASHSCOPE_API_KEY` to `.env`. Do not include
the key in the submitted project.

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_local_windows.ps1
```

macOS or Linux:

```sh
./scripts/run_local_unix.sh
```

Open <http://127.0.0.1:5173>, create a trimester, and open the clearly labelled
`grader-test-case/images/` folder at the project root. Upload the matching image
for each module:

- `HSC1007`
- `HSC1009`
- `HSC1010`
- `OTY1103`

Confirm that the assessment schedule and study plan appear, then reload the
page and reopen the saved trimester.
