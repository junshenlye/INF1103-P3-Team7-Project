"""Legacy function adapters around the repository and DataManager contracts."""

import os
from .errors import DataManagerError, format_data_error
from .serializers import ResultSerializer, calculate_module_snapshot_hash
from .postgres_repository import (
    PostgresRepository,
    create_connection,
    DATABASE_ENVIRONMENT_VARIABLE,
)
from .repository import PlanningRepository
from .manager import DataManager


def is_configured(database_url=None):
    """Return whether a database URL is available for optional persistence."""
    return bool(database_url or os.getenv(DATABASE_ENVIRONMENT_VARIABLE))


def check_connection(database_url=None):
    return PostgresRepository(database_url).check_connection()


def create_project(name, week_count=14, database_url=None):
    return PostgresRepository(database_url).create_project(name, week_count)


def get_or_create_project(name, week_count=14, project_id=None, database_url=None):
    return PostgresRepository(database_url).get_or_create_project(
        name, week_count, project_id
    )


def list_projects(database_url=None):
    return PostgresRepository(database_url).list_projects()


def get_project(project_id, database_url=None):
    return PostgresRepository(database_url).get_project(project_id)


def start_pipeline_run(project_id, requested_module_count, database_url=None):
    return PostgresRepository(database_url).start_pipeline_run(
        project_id, requested_module_count
    )


def save_pipeline_result(project_id, run_id, payload, errors, database_url=None):
    return PostgresRepository(database_url).save_pipeline_result(
        project_id, run_id, payload, errors
    )


def get_latest_pipeline_result(project_id, database_url=None):
    return PostgresRepository(database_url).get_latest_pipeline_result(project_id)


def list_pipeline_runs(project_id, database_url=None):
    return PostgresRepository(database_url).list_pipeline_runs(project_id)


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
    return PostgresRepository(database_url).save_recommendation(
        project_id,
        recommendation_type,
        modules,
        preferences,
        recommendation,
        prompt_version,
        model_name,
    )


def list_recommendations(project_id, database_url=None):
    return PostgresRepository(database_url).list_recommendations(project_id)


def set_recommendation_status(project_id, recommendation_id, status, database_url=None):
    return PostgresRepository(database_url).set_recommendation_status(
        project_id, recommendation_id, status
    )


def get_project_overview(project_id, database_url=None):
    return DataManager(PostgresRepository(database_url)).get_project_overview(
        project_id
    )
