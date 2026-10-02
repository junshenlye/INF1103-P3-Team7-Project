# Stackplan MVP

Stackplan extracts assessment evidence from any number of modules and returns
canonical module data for the frontend. Logic Manager preserves the extracted
facts and adds one deterministic schedule weight to each graded or bonus item.

## Flow

```text
Frontend Demo
  -> IO Manager validates and normalizes all modules
  -> AI Manager extracts assessment facts and uncertainty
  -> Logic Manager calculates assessment weightage × module credits
  -> Data Manager stores input, extraction, and the final result
  -> Frontend sorts the assessments and builds its own timeline
```

`src/main.py` remains the orchestration layer and the frontend uses the
`{"modules": [...]}` request.

## Deterministic calculations

- Schedule weight = extracted assessment weightage × module credits.
- Module and assessment order is preserved.
- No rank, deadline tier, pressure, overlap, cluster, or timeline is calculated.
- Recurrence, dates, weeks, comments, assumptions, confidence, and missing
  information are copied unchanged for the frontend.

Each module runs through the same three-stage chain: a fast image relevance
precheck, evidence-only context extraction, and text-only schedule reasoning.
The default models are `qwen3.7-flash`, `qwen3.7-plus`, and `qwen3.7-plus`
respectively. Override them with `AI_PRECHECK_MODEL`, `AI_CONTEXT_MODEL`, and
`AI_REASONING_MODEL`.

The reasoning stage uses non-thinking mode with a compact output limit because
the evidence has already been extracted and the output follows a strict schema.
Each model call has a 45-second limit with no automatic retry, and the complete AI request
has a 240-second limit. Override these with `AI_MODEL_TIMEOUT_SECONDS`,
`AI_MODEL_RETRIES`, and `AI_REQUEST_TIMEOUT_SECONDS`.

Multiple modules use this same chain concurrently. Two model calls are in flight
by default (`AI_MAX_CONCURRENT_REQUESTS`) and results remain in frontend order.
Task 3
classifies visible rows as graded, aggregate, bonus, ungraded, or uncertain.
Only unusable input or a processing failure rejects the request.

When one module fails but another succeeds, the request returns
`partial_success`. Failed modules are listed separately and successful modules
continue through Logic Manager and Data Manager.

### Code map

- `src/io_manager.py`: validates frontend fields once and classifies each accepted
  path into canonical `images` or `documents` data for downstream managers.
- `src/ai_manager.py`: the AI boundary. It owns the three prompts, model requests,
  response schemas, one normalization pass, and one grouped module-failure payload.
- `process`: is the synchronous Flask-compatible wrapper around `process_async`.
  The async function gathers independent requests in their original order. Each
  reply is normalized once before the final result is assembled.
- `_extract_module`: visibly runs precheck, context extraction, and final
  reasoning for one module. A module failure stays isolated to that module.
- `_call_model`: is the asynchronous OpenAI-compatible transport used by the
  extraction flow.
- `_pacing_schema`: defines the strict model response contract, including
  recurring weight scope.
- `_normalize_module_result`: converts the final reasoning output to the
  canonical module shape without repairing fractional weights or inferred weeks.
- `src/logic_manager.py`: preserves canonical module data, calculates schedule
  weight, and groups hard AI failures.

The AI Manager has one multi-module extraction path; each module is processed
independently through the same prompt, schema, and normalization flow.

## Run

Copy `.env.example` to `.env` and provide `DASHSCOPE_API_KEY`.

```sh
docker compose up -d --build backend

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python frontend-demo/app.py
```

- Frontend: http://127.0.0.1:5050
- Extraction endpoint: http://127.0.0.1:5050/api/extractions
- Stored module data: http://127.0.0.1:5050/api/data
- Health: http://127.0.0.1:5050/health

The frontend accepts images, PDF, DOCX, and simple text-based files. Uploads
exist only for the duration of one request. The Flask frontend runs on the host
and sends newline-delimited JSON to the persistent backend container at
`127.0.0.1:8000`. The backend container communicates with PostgreSQL through the
Compose network. There is no local JSON persistence fallback.

The Compose database is intentionally disposable: PostgreSQL stores its data in
container memory rather than a named or host volume. `docker compose restart db`
or `docker compose down` clears the database so the next start is a clean test
run. If `DATABASE_URL` is unset, storage is unavailable rather than silently
switching to another persistent data source.

After an extraction, the frontend shows the measured IO Manager, AI Manager,
Logic Manager, Data Manager, and end-to-end request runtimes. It also shows each
module/model/stage duration and any skipped module. This last-run display is kept
in the browser session; the assessment data itself is loaded from PostgreSQL
through Data Manager.

The frontend scheduler derives its columns from the highest supplied `due_week`.
Weeks are displayed horizontally. Assessments with the same due week are stacked
vertically by descending `schedule_weight`. Recurring or incomplete items without
a due week remain in a separate timing-missing list and are never expanded or
placed by assumption.

## Test

```sh
python -m pytest -q
```
