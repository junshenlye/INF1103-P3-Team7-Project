# Stackplan

This repository is intentionally reduced to a single command-line workflow.
There is no web server, database, frontend runtime, or manager layer.

## Local use

Create `.env` from `.env.example`, add a DashScope API key, and install the
dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m src.main test_case/INF1103.png
```

You can supply multiple image or UTF-8 text files and override the instruction:

```sh
python -m src.main notes.txt screenshot.png --prompt "Extract the deadlines."
```

Supported inputs are PNG, JPEG, WebP, GIF, TXT, Markdown, CSV, and JSON. The
model response is written directly to standard output; the CLI does not persist
data or reshape the response.

## Docker

Build the CLI image:

```sh
docker build -t stackplan .
```

Run it with a local evidence directory mounted read-only:

```sh
docker run --rm \
  --env-file .env \
  --volume "$PWD/test_case:/evidence:ro" \
  stackplan /evidence/INF1103.png
```

Arguments after the image name are passed directly to the CLI. Run
`docker run --rm stackplan --help` to see all options.
