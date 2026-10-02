"""Persist pipeline inputs and outputs without owning business logic."""

import json
import logging
import os


LOGGER = logging.getLogger(__name__)
_DATABASE_FAILURE = object()


def initialize_storage():
    """Create one disposable PostgreSQL slot for the current plan."""
    result = _run_database_operation(
        _ensure_schema,
        missing_error="DATABASE_URL is required; local file persistence is disabled",
        failure_error="Could not initialize PostgreSQL",
    )
    return result is not _DATABASE_FAILURE


def storage_is_ready():
    """Return whether PostgreSQL can answer a small query."""
    return _run_database_operation(_ping_database) is True


def save_plan(plan):
    """Replace the single disposable plan."""
    result = _run_database_operation(
        _replace_plan,
        plan,
        missing_error="Cannot save a plan without DATABASE_URL",
        failure_error="Could not save the assessment plan",
    )
    return result is not _DATABASE_FAILURE


def save(input_data, ai_result, logic_result):
    """Store the normalized input, canonical AI data, and weighted module data."""
    safe_modules = []
    for module in input_data.get("modules", []):
        safe_files = []
        for image in module.get("images", []):
            safe_files.append({"name": os.path.basename(image["path"])})
        for document in module.get("documents", []):
            safe_files.append({"name": os.path.basename(document["path"])})

        safe_module = {
            "module_name": module.get("module_name"),
            "credit_units": module.get("credit_units"),
            "additional_context": module.get("additional_context", ""),
            "files": safe_files,
        }
        safe_modules.append(safe_module)

    safe_input = {
        "calendar": input_data.get("calendar", {"recess_weeks": []}),
        "modules": safe_modules,
    }
    record = {
        "input_data": safe_input,
        "ai_result": ai_result,
        "logic_result": logic_result,
    }
    return save_plan(record)


def load_plan():
    """Load the current plan or an empty dashboard."""
    stored_plan = _run_database_operation(
        _fetch_plan,
        failure_error="Could not load the assessment plan",
    )
    if stored_plan is _DATABASE_FAILURE or stored_plan is None:
        return _empty_plan()
    record = json.loads(stored_plan) if isinstance(stored_plan, str) else stored_plan
    if isinstance(record, dict) and isinstance(record.get("logic_result"), dict):
        return record["logic_result"]
    LOGGER.error("Stored plan does not contain the current logic_result schema")
    return _empty_plan()


def _run_database_operation(operation, *args, missing_error=None, failure_error=None):
    """Run one operation with the configured database connection."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        if missing_error:
            LOGGER.error(missing_error)
        return _DATABASE_FAILURE

    try:
        with _connect(database_url) as connection:
            return operation(connection, *args)
    except Exception:
        if failure_error:
            LOGGER.exception(failure_error)
        return _DATABASE_FAILURE


def _ping_database(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        return cursor.fetchone()[0] == 1


def _replace_plan(connection, plan):
    _ensure_schema(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO current_plan (slot, plan)
            VALUES (TRUE, %s::jsonb)
            ON CONFLICT (slot) DO UPDATE SET plan = EXCLUDED.plan
            """,
            (json.dumps(plan),),
        )


def _fetch_plan(connection):
    _ensure_schema(connection)
    with connection.cursor() as cursor:
        cursor.execute("SELECT plan FROM current_plan WHERE slot = TRUE")
        row = cursor.fetchone()
    return None if row is None else row[0]


def _empty_plan():
    """Return an empty module result."""
    return {"modules": []}


def _connect(database_url):
    """Open one short-lived database connection."""
    import psycopg

    return psycopg.connect(database_url)


def _ensure_schema(connection):
    """Recreate the disposable table after a database restart when needed."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS current_plan (
                slot BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (slot),
                plan JSONB NOT NULL
            )
            """
        )
