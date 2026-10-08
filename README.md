# Stackplan

This repository starts with a small command-line intake workflow. It reads a
module payload, copies each module file into `/tmp/stackplan-intake`, and returns
the transformed data for the next pipeline stage.

## Local use

Create an `intake.json` payload:

```json
{
  "module_count": 2,
  "modules": [
    {
      "module_title": "INF1103",
      "credit": 4,
      "file_path": "test_case/INF1103.png"
    },
    {
      "module_title": "INF1104",
      "credit": 4,
      "file_path": "test_case/INF1104.png"
    }
  ]
}
```

Install the dependencies and pass the payload file to the CLI:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m src.main intake.json
```

Each successful output module preserves `module_title` and `credit` and replaces
`file_path` with `stored_file_path`. Failed modules are excluded from the clean
AI payload and their messages are collected in a separate pipeline error list.
Final error output and exit codes are deferred until the AI, Logic, and Data
Manager stages are connected. Relative file paths are resolved from the payload
file's directory.

Payload validation intentionally checks only the basic structure and types:
`module_count` and `credit` must be integers, `modules` must be an array, and
`module_title` must be a string. `copy_to_tmp()` separately checks that each
`file_path` is a string and points to an available local file. File-type
validation and AI processing are not part of this integration.

## Docker

Build the CLI image:

```sh
docker build -t stackplan .
```

Run it with a local evidence directory mounted read-only:

```sh
docker run --rm \
  --volume "$PWD:/workspace:ro" \
  stackplan /workspace/intake.json
```

The IO manager creates `/tmp/stackplan-intake` when it copies the first file.
This directory is only working storage, and its cached files disappear with the
container when `--rm` removes it.
