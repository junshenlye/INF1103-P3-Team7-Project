"""Test isolation: no live AI and destructive fixtures only in the test database."""

import os
from urllib.parse import urlparse

import pytest

from src import data_manager
from src.ai_manager import qwen_client


def pytest_collection_modifyitems(items):
    for item in items:
        if "database_url" in item.fixturenames:
            item.add_marker(pytest.mark.integration)


def pytest_sessionfinish(session):
    if os.getenv("STACKPLAN_REQUIRE_DATABASE") == "1":
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter and reporter.stats.get("skipped"):
            session.exitstatus = 1


@pytest.fixture(autouse=True)
def no_live_ai(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Automated tests must inject a fake Qwen provider.")

    monkeypatch.setattr(qwen_client, "AsyncOpenAI", forbidden)
    monkeypatch.setattr(qwen_client, "load_dotenv", lambda: None)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)


@pytest.fixture
def database_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        if os.getenv("STACKPLAN_REQUIRE_DATABASE") == "1":
            pytest.fail("Required disposable PostgreSQL database is not configured.")
        pytest.skip("Select the full verification gate for PostgreSQL tests.")
    parsed = urlparse(url)
    if (
        os.getenv("STACKPLAN_TEST_DATABASE") != "1"
        or parsed.path != "/stackplan_test"
        or parsed.username != "stackplan_test"
        or parsed.hostname not in {"test-database", "localhost", "127.0.0.1"}
    ):
        pytest.fail(
            "Refusing destructive fixtures outside the isolated stackplan_test database."
        )

    def clean():
        try:
            with data_manager.create_connection(url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "TRUNCATE recommendations, pipeline_runs, projects RESTART IDENTITY CASCADE"
                    )
        except data_manager.DataManagerError as error:
            pytest.fail(f"Required PostgreSQL database is unavailable: {error}")

    clean()
    try:
        yield url
    finally:
        clean()


@pytest.fixture(
    params=["memory", pytest.param("postgres", marks=pytest.mark.integration)]
)
def repository(request):
    if request.param == "postgres":
        return data_manager.PostgresRepository(request.getfixturevalue("database_url"))
    from tests.fakes import MemoryRepository

    return MemoryRepository()
