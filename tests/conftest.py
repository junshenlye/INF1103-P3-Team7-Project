"""Shared fixtures for function and workflow tests."""

import os

import pytest

from src import data_manager


@pytest.fixture
def database_url():
    """Return a clean Compose test database or skip database-only tests."""
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required for PostgreSQL tests.")
    try:
        connection = data_manager.create_connection(url)
    except data_manager.DataManagerError:
        pytest.skip("PostgreSQL test database is unavailable.")
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE recommendations, pipeline_runs, projects
                RESTART IDENTITY CASCADE
                """
            )
    yield url
    with data_manager.create_connection(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE recommendations, pipeline_runs, projects
                RESTART IDENTITY CASCADE
                """
            )
