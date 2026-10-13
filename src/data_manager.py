"""Persist projects, pipeline results and AI recommendations in PostgreSQL.

The module deliberately keeps SQL behind a small procedural interface. Other
managers continue to work with dictionaries and do not know how data is stored.
"""

from hashlib import sha256
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


DATABASE_ENVIRONMENT_VARIABLE = "DATABASE_URL"


# Use a built-in exception through a descriptive alias. This keeps callers
# readable while satisfying the project's functions-only requirement.
DataManagerError = RuntimeError


def format_data_error(error):
    """Return one hard Data Manager error using the pipeline prefix."""
    return f"Data Manager error: {error}"


def is_configured(database_url=None):
    """Return whether a database URL is available for optional persistence."""
    return bool(database_url or os.getenv(DATABASE_ENVIRONMENT_VARIABLE))


def create_connection(database_url=None):
    """Open one dictionary-row PostgreSQL connection.

    Connections are intentionally short lived. Every public operation uses a
    context manager so commits, rollbacks and closure are easy to audit.
    """
    resolved_url = database_url or os.getenv(DATABASE_ENVIRONMENT_VARIABLE)
    if not resolved_url:
        raise DataManagerError("DATABASE_URL must be configured.")
    try:
        return psycopg.connect(resolved_url, row_factory=dict_row)
    except psycopg.Error as error:
        raise DataManagerError("Could not connect to PostgreSQL.") from error


def check_connection(database_url=None):
    """Return ``True`` when PostgreSQL accepts a simple query."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS healthy")
                return cursor.fetchone()["healthy"] == 1
    except psycopg.Error as error:
        raise DataManagerError("PostgreSQL health check failed.") from error


def create_project(name, week_count=14, database_url=None):
    """Create one project and return its database record."""
    if not isinstance(name, str) or not name.strip():
        raise DataManagerError("Project name must be a non-empty string.")
    if type(week_count) is not int or not 1 <= week_count <= 52:
        raise DataManagerError("week_count must be an integer from 1 to 52.")

    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO projects (name, week_count)
                    VALUES (%s, %s)
                    RETURNING *
                    """,
                    (name.strip(), week_count),
                )
                return cursor.fetchone()
    except psycopg.errors.UniqueViolation as error:
        raise DataManagerError(f"Project '{name.strip()}' already exists.") from error
    except psycopg.Error as error:
        raise DataManagerError("Could not create the project.") from error


def get_or_create_project(name, week_count=14, project_id=None, database_url=None):
    """Return an existing requested project or create one by name."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                if project_id is not None:
                    cursor.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
                    project = cursor.fetchone()
                    if project is None:
                        raise DataManagerError(f"Project {project_id} does not exist.")
                    return project

                if not isinstance(name, str) or not name.strip():
                    raise DataManagerError("Project name must be a non-empty string.")
                cursor.execute(
                    """
                    INSERT INTO projects (name, week_count)
                    VALUES (%s, %s)
                    ON CONFLICT (name) DO UPDATE SET updated_at = NOW()
                    RETURNING *
                    """,
                    (name.strip(), week_count),
                )
                return cursor.fetchone()
    except DataManagerError:
        raise
    except psycopg.Error as error:
        raise DataManagerError("Could not load or create the project.") from error


def list_projects(database_url=None):
    """Return projects ordered by their most recent activity."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM projects ORDER BY updated_at DESC, id DESC"
                )
                return cursor.fetchall()
    except psycopg.Error as error:
        raise DataManagerError("Could not list projects.") from error


def get_project(project_id, database_url=None):
    """Return one project or ``None`` when its ID is unknown."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
                return cursor.fetchone()
    except psycopg.Error as error:
        raise DataManagerError("Could not load the project.") from error


def start_pipeline_run(project_id, requested_module_count, database_url=None):
    """Create a running pipeline record and return its ID."""
    if type(requested_module_count) is not int or requested_module_count < 0:
        raise DataManagerError("requested_module_count must be a non-negative integer.")
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO pipeline_runs (project_id, requested_module_count)
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (project_id, requested_module_count),
                )
                return cursor.fetchone()["id"]
    except psycopg.Error as error:
        raise DataManagerError("Could not start the pipeline run.") from error


def save_pipeline_result(
    project_id,
    run_id,
    payload,
    errors,
    source_hashes=None,
    prompt_version="unknown",
    model_name="unknown",
    database_url=None,
):
    """Atomically save module revisions and complete a pipeline run.

    The newest successful revision becomes active automatically. Older
    revisions remain stored for audit history but are no longer displayed.
    """
    source_hashes = source_hashes or {}
    modules = payload.get("modules", []) if isinstance(payload, dict) else []
    if payload is None:
        status = "failed"
    elif errors:
        status = "partial"
    else:
        status = "completed"

    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                for module in modules:
                    module_title = module["module_title"]
                    cursor.execute(
                        """
                        SELECT COALESCE(MAX(revision), 0) AS latest_revision
                        FROM module_results
                        WHERE project_id = %s AND module_title = %s
                        """,
                        (project_id, module_title),
                    )
                    revision_state = cursor.fetchone()
                    revision = revision_state["latest_revision"] + 1
                    cursor.execute(
                        """
                        UPDATE module_results SET is_confirmed = FALSE
                        WHERE project_id = %s AND module_title = %s
                          AND is_confirmed
                        """,
                        (project_id, module_title),
                    )
                    cursor.execute(
                        """
                        INSERT INTO module_results (
                            project_id, run_id, module_title, credit, source_hash,
                            prompt_version, model_name, revision, is_confirmed,
                            module_payload
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            project_id,
                            run_id,
                            module_title,
                            module["credit"],
                            source_hashes.get(module_title),
                            prompt_version,
                            model_name,
                            revision,
                            True,
                            Jsonb(module),
                        ),
                    )

                cursor.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = %s,
                        processed_module_count = %s,
                        result_payload = %s,
                        errors = %s,
                        completed_at = NOW()
                    WHERE id = %s AND project_id = %s
                    """,
                    (
                        status,
                        len(modules),
                        Jsonb(payload) if payload is not None else None,
                        Jsonb(errors),
                        run_id,
                        project_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise DataManagerError("Pipeline run does not exist.")
                cursor.execute(
                    "UPDATE projects SET updated_at = NOW() WHERE id = %s",
                    (project_id,),
                )
    except DataManagerError:
        raise
    except (KeyError, TypeError) as error:
        raise DataManagerError("Pipeline result has an invalid structure.") from error
    except psycopg.Error as error:
        raise DataManagerError("Could not save the pipeline result.") from error


def get_confirmed_modules(project_id, database_url=None):
    """Return the active confirmed module payloads for one project."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT module_payload
                    FROM module_results
                    WHERE project_id = %s AND is_confirmed
                    ORDER BY module_title
                    """,
                    (project_id,),
                )
                return [row["module_payload"] for row in cursor.fetchall()]
    except psycopg.Error as error:
        raise DataManagerError("Could not load confirmed modules.") from error


def list_module_revisions(project_id, database_url=None):
    """Return all stored module revisions for review, newest first."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, module_title, credit, source_hash, prompt_version,
                           model_name, revision, is_confirmed, module_payload,
                           created_at
                    FROM module_results
                    WHERE project_id = %s
                    ORDER BY module_title, revision DESC
                    """,
                    (project_id,),
                )
                return cursor.fetchall()
    except psycopg.Error as error:
        raise DataManagerError("Could not list module revisions.") from error


def list_pipeline_runs(project_id, database_url=None):
    """Return a project's processing history, newest first."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM pipeline_runs
                    WHERE project_id = %s
                    ORDER BY started_at DESC, id DESC
                    """,
                    (project_id,),
                )
                return cursor.fetchall()
    except psycopg.Error as error:
        raise DataManagerError("Could not list pipeline runs.") from error


def confirm_module_revision(project_id, module_title, revision, database_url=None):
    """Make one candidate revision active without deleting its history."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id FROM module_results
                    WHERE project_id = %s AND module_title = %s AND revision = %s
                    """,
                    (project_id, module_title, revision),
                )
                selected = cursor.fetchone()
                if selected is None:
                    raise DataManagerError("Module revision does not exist.")
                cursor.execute(
                    """
                    UPDATE module_results SET is_confirmed = FALSE
                    WHERE project_id = %s AND module_title = %s AND is_confirmed
                    """,
                    (project_id, module_title),
                )
                cursor.execute(
                    "UPDATE module_results SET is_confirmed = TRUE WHERE id = %s",
                    (selected["id"],),
                )
                cursor.execute(
                    "UPDATE projects SET updated_at = NOW() WHERE id = %s",
                    (project_id,),
                )
                return True
    except DataManagerError:
        raise
    except psycopg.Error as error:
        raise DataManagerError("Could not confirm the module revision.") from error


def save_confirmed_module_edit(project_id, module, database_url=None):
    """Create a confirmed student-edited revision without deleting AI history."""
    if not isinstance(module, dict):
        raise DataManagerError("Edited module must be a dictionary.")
    module_title = module.get("module_title")
    credit = module.get("credit")
    if not isinstance(module_title, str) or type(credit) is not int or credit <= 0:
        raise DataManagerError("Edited module metadata is invalid.")

    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(revision), 0) AS latest_revision,
                           (ARRAY_AGG(source_hash ORDER BY revision DESC))[1] AS source_hash
                    FROM module_results
                    WHERE project_id = %s AND module_title = %s
                    """,
                    (project_id, module_title),
                )
                state = cursor.fetchone()
                if state["latest_revision"] == 0:
                    raise DataManagerError("Module does not exist in this project.")
                cursor.execute(
                    """
                    UPDATE module_results SET is_confirmed = FALSE
                    WHERE project_id = %s AND module_title = %s AND is_confirmed
                    """,
                    (project_id, module_title),
                )
                cursor.execute(
                    """
                    INSERT INTO module_results (
                        project_id, module_title, credit, source_hash,
                        prompt_version, model_name, revision, is_confirmed,
                        module_payload
                    )
                    VALUES (%s, %s, %s, %s, 'manual', 'student-edit', %s, TRUE, %s)
                    RETURNING *
                    """,
                    (
                        project_id,
                        module_title,
                        credit,
                        state["source_hash"],
                        state["latest_revision"] + 1,
                        Jsonb(module),
                    ),
                )
                saved = cursor.fetchone()
                cursor.execute(
                    "UPDATE projects SET updated_at = NOW() WHERE id = %s",
                    (project_id,),
                )
                return saved
    except DataManagerError:
        raise
    except psycopg.Error as error:
        raise DataManagerError("Could not save the edited module.") from error


def calculate_module_snapshot_hash(modules):
    """Return a deterministic module snapshot hash for recommendation audits."""
    canonical = json.dumps(modules, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def save_recommendation(
    project_id,
    recommendation_type,
    modules,
    preferences,
    recommendation,
    prompt_version,
    model_name,
    database_url=None,
):
    """Store one AI recommendation candidate and return its record."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO recommendations (
                        project_id, recommendation_type, input_revision_hash,
                        prompt_version, model_name, preferences,
                        recommendation_payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        project_id,
                        recommendation_type,
                        calculate_module_snapshot_hash(modules),
                        prompt_version,
                        model_name,
                        Jsonb(preferences),
                        Jsonb(recommendation),
                    ),
                )
                saved_recommendation = cursor.fetchone()
                cursor.execute(
                    "UPDATE projects SET updated_at = NOW() WHERE id = %s",
                    (project_id,),
                )
                return saved_recommendation
    except psycopg.Error as error:
        raise DataManagerError("Could not save the recommendation.") from error


def list_recommendations(project_id, database_url=None):
    """Return a project's recommendation history, newest first."""
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM recommendations
                    WHERE project_id = %s
                    ORDER BY created_at DESC, id DESC
                    """,
                    (project_id,),
                )
                return cursor.fetchall()
    except psycopg.Error as error:
        raise DataManagerError("Could not list recommendations.") from error


def set_recommendation_status(
    project_id,
    recommendation_id,
    status,
    database_url=None,
):
    """Accept or dismiss one recommendation candidate."""
    if status not in {"candidate", "accepted", "dismissed"}:
        raise DataManagerError("Recommendation status is invalid.")
    try:
        with create_connection(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT recommendation_type FROM recommendations
                    WHERE id = %s AND project_id = %s
                    """,
                    (recommendation_id, project_id),
                )
                recommendation = cursor.fetchone()
                if recommendation is None:
                    raise DataManagerError("Recommendation does not exist.")
                if status == "accepted":
                    cursor.execute(
                        """
                        UPDATE recommendations
                        SET status = 'dismissed', updated_at = NOW()
                        WHERE project_id = %s
                          AND recommendation_type = %s
                          AND status = 'accepted'
                        """,
                        (project_id, recommendation["recommendation_type"]),
                    )
                cursor.execute(
                    """
                    UPDATE recommendations
                    SET status = %s, updated_at = NOW()
                    WHERE id = %s AND project_id = %s
                    RETURNING *
                    """,
                    (status, recommendation_id, project_id),
                )
                return cursor.fetchone()
    except DataManagerError:
        raise
    except psycopg.Error as error:
        raise DataManagerError("Could not update recommendation status.") from error


def get_project_overview(project_id, database_url=None):
    """Return frontend-ready stored project data without running AI."""
    project = get_project(project_id, database_url)
    if project is None:
        return None
    project["modules"] = get_confirmed_modules(project_id, database_url)
    project["module_revisions"] = list_module_revisions(project_id, database_url)
    project["pipeline_runs"] = list_pipeline_runs(project_id, database_url)
    project["recommendations"] = list_recommendations(project_id, database_url)
    return project


def hash_file(file_path):
    """Return the SHA-256 digest of one IO-validated source file."""
    digest = sha256()
    with Path(file_path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_files(file_paths):
    """Return one order-sensitive digest for a module's evidence images."""
    digest = sha256()
    for file_path in file_paths:
        digest.update(hash_file(file_path).encode("ascii"))
    return digest.hexdigest()
