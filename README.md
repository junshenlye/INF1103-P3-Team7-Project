# Stackplan

The command-line workflow passes module evidence through the IO Manager and AI
Manager. IO validates and stores images; AI interprets and normalizes assessment
information for scheduling.

## Local use

The repository includes `test_payload.json`. Its format is:

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

Create the local environment file and add your DashScope API key:

```sh
cp .env.example .env
```

```dotenv
DASHSCOPE_API_KEY="your-key"
DASHSCOPE_BASE_URL="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
```

Install the dependencies and pass the payload file to the CLI:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m src.main test_payload.json
```

The CLI emits one JSON object containing `payload` and `errors`. Failed modules
are excluded from the clean payload, while their hard errors remain in the
shared error list for later managers. AI uncertainties stay with their module as
`follow_ups` metadata and are not promoted to hard errors. Relative file paths
are resolved from the payload file's directory.

IO payload validation checks the basic structure and types: `module_count` and
`credit` must be integers, `modules` must be an array, and `module_title` must
be a string. `validate_and_store_images()` accepts readable JPEG and PNG images
up to 10 MB and stores successful files in temporary working storage. The AI
Manager receives only this validated IO output.

IO failures are kept outside the AI payload as strings beginning with
`IO Manager error:`. Invalid modules are removed, the remaining modules
continue, and the collected messages can be passed to the future logging layer.

## Testing

Run the offline unit tests without making Qwen requests:

```sh
source .venv/bin/activate
PYTHONPATH=. pytest -q
```

Run a lower-cost live AI Manager check with one representative module:

```sh
docker compose build
./scripts/run_quick_test.sh
```

The quick payload uses INF1104 and exercises repeated tutorials, group weights,
fixed teaching weeks and the final examination. A relevant module makes one
Qwen Flash relevance request and two Qwen Plus reasoning requests.

## Logging

The CLI enables progress logs for the pipeline and its managers. Errors remain
in the returned error list for the next pipeline stage. Logs are not stored in
files; Docker captures the console stream automatically. Each Qwen HTTP request
logs its module, processing pass, model, outcome and elapsed provider time. The
measurement starts after the concurrency slot is acquired, so queue time is not
included.

## Docker

Build and run the CLI with Docker Compose:

```sh
docker compose build
docker compose run --rm stackplan
```

Compose reads `.env`, mounts the repository as read-only input, and supplies
`test_payload.json` to the container. These defaults are defined in
`compose.yaml`, so credentials do not need to appear in the run command.

The default Compose command uses `test_payload.json` and runs all four example
modules. Use the quick test above during normal development to reduce token use.

To run the image without Compose, pass the runtime environment explicitly:

```sh
docker run --rm \
  --env-file .env \
  --volume "$PWD:/workspace:ro" \
  stackplan /workspace/test_payload.json
```

The Dockerfile does not copy `.env` into the image. Secrets copied during a
build remain in image layers, so the `.dockerignore` entry for `.env` should
remain in place.

The IO manager creates `/tmp/stackplan-intake` when it copies the first file.
This directory is only working storage, and its cached files disappear with the
container when `--rm` removes it.
