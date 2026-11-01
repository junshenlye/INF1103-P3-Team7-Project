"""PostgreSQL repository: SQL, transactions and connection ownership only."""

from contextlib import nullcontext
import os
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .errors import DataManagerError
from .serializers import calculate_module_snapshot_hash

DATABASE_ENVIRONMENT_VARIABLE = "DATABASE_URL"


def create_connection(database_url=None):
    """Open one dictionary-row PostgreSQL connection.

    Connections are intentionally short lived. Every public operation uses a
    context manager so commits, rollbacks and closure are easy to audit.
    """
    resolved_url = database_url or os.getenv(DATABASE_ENVIRONMENT_VARIABLE)
    if not resolved_url:
        raise DataManagerError("DATABASE_URL must be configured.")
    try:
        return psycopg.connect(
            resolved_url,
            row_factory=dict_row,
            connect_timeout=5,
            options="-c statement_timeout=10000 -c lock_timeout=5000",
        )
    except psycopg.Error as error:
        raise DataManagerError("Could not connect to PostgreSQL.") from error


class PostgresRepository:
    def __init__(self, database_url=None, connection_factory=None):
        self.database_url = database_url
        self._connection_factory = connection_factory

    def _connect(self):
        return (
            self._connection_factory()
            if self._connection_factory
            else create_connection(self.database_url)
        )

    def check_connection(self, database_url=None):
        """Return ``True`` when PostgreSQL accepts a simple query."""
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1 AS healthy")
                    return cursor.fetchone()["healthy"] == 1
        except psycopg.Error as error:
            raise DataManagerError("PostgreSQL health check failed.") from error

    def create_project(self, name, week_count=14):
        """Create one project and return its database record."""
        if not isinstance(name, str) or not name.strip():
            raise DataManagerError("Project name must be a non-empty string.")
        if type(week_count) is not int or not 1 <= week_count <= 52:
            raise DataManagerError("week_count must be an integer from 1 to 52.")

        try:
            with self._connect() as connection:
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
            raise DataManagerError(
                f"Project '{name.strip()}' already exists."
            ) from error
        except psycopg.Error as error:
            raise DataManagerError("Could not create the project.") from error

    def get_or_create_project(self, name, week_count=14, project_id=None):
        """Return an existing requested project or create one by name."""
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    if project_id is not None:
                        cursor.execute(
                            "SELECT * FROM projects WHERE id = %s", (project_id,)
                        )
                        project = cursor.fetchone()
                        if project is None:
                            raise DataManagerError(
                                f"Project {project_id} does not exist."
                            )
                        return project

                    if not isinstance(name, str) or not name.strip():
                        raise DataManagerError(
                            "Project name must be a non-empty string."
                        )
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

    def list_projects(self, database_url=None):
        """Return projects ordered by their most recent activity."""
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM projects ORDER BY updated_at DESC, id DESC"
                    )
                    return cursor.fetchall()
        except psycopg.Error as error:
            raise DataManagerError("Could not list projects.") from error

    def get_project(self, project_id):
        """Return one project or ``None`` when its ID is unknown."""
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM projects WHERE id = %s", (project_id,)
                    )
                    return cursor.fetchone()
        except psycopg.Error as error:
            raise DataManagerError("Could not load the project.") from error

    def start_pipeline_run(self, project_id, requested_module_count):
        """Create a running pipeline record and return its ID."""
        if type(requested_module_count) is not int or requested_module_count < 0:
            raise DataManagerError(
                "requested_module_count must be a non-negative integer."
            )
        try:
            with self._connect() as connection:
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
        self,
        project_id,
        run_id,
        payload,
        errors,
    ):
        """Atomically save the complete result and finish a pipeline run."""
        modules = payload.get("modules", []) if isinstance(payload, dict) else []
        if payload is None:
            status = "failed"
        elif errors:
            status = "partial"
        else:
            status = "completed"

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
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
        except psycopg.Error as error:
            raise DataManagerError("Could not save the pipeline result.") from error

    def get_latest_pipeline_result(self, project_id):
        """Return the newest complete saved payload without recomputing it."""
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT result_payload
                        FROM pipeline_runs
                        WHERE project_id = %s AND result_payload IS NOT NULL
                        ORDER BY completed_at DESC NULLS LAST, id DESC
                        LIMIT 1
                        """,
                        (project_id,),
                    )
                    row = cursor.fetchone()
                    return row["result_payload"] if row is not None else None
        except psycopg.Error as error:
            raise DataManagerError(
                "Could not load the latest pipeline result."
            ) from error

    def list_pipeline_runs(self, project_id):
        """Return a project's processing history, newest first."""
        try:
            with self._connect() as connection:
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

    def save_recommendation(
        self,
        project_id,
        recommendation_type,
        modules,
        preferences,
        recommendation,
        prompt_version,
        model_name,
    ):
        """Store one AI recommendation candidate and return its record."""
        try:
            with self._connect() as connection:
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

    def list_recommendations(self, project_id):
        """Return a project's recommendation history, newest first."""
        try:
            with self._connect() as connection:
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
        self,
        project_id,
        recommendation_id,
        status,
    ):
        """Accept or dismiss one recommendation candidate."""
        if status not in {"candidate", "accepted", "dismissed"}:
            raise DataManagerError("Recommendation status is invalid.")
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM projects WHERE id = %s FOR UPDATE",
                        (project_id,),
                    )
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

    def complete_run(self, project_id, run_id, payload, errors, recommendation=None):
        """Commit result and automatic advice together, or roll both back."""
        try:
            with self._connect() as connection:
                transaction = PostgresRepository(
                    self.database_url, lambda: nullcontext(connection)
                )
                transaction.save_pipeline_result(project_id, run_id, payload, errors)
                if recommendation is not None:
                    transaction.save_recommendation(
                        project_id=project_id, **recommendation
                    )
        except psycopg.Error as error:
            raise DataManagerError(
                "Could not commit the pipeline result and advice."
            ) from error
