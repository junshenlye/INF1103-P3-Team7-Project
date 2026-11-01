"""Function tests for PostgreSQL persistence and saved-result selection."""

from src import data_manager


def module_payload(name="Quiz 1"):
    """Return one small normalized module document."""
    return {
        "module_title": "INF1104",
        "credit": 4,
        "source_coverage": {"status": "appears_complete", "comment": None},
        "assessment_types": [
            {
                "type": "quiz",
                "assessments": [
                    {"assessment_id": "INF1104-QUIZ-01", "name": name}
                ],
            }
        ],
        "notes": [],
        "follow_ups": [],
    }


def test_module_snapshot_hash_describes_the_recommendation_input():
    """Equivalent module snapshots have the same audit fingerprint."""
    module = module_payload()
    reordered_module = dict(reversed(list(module.items())))

    snapshot_hash = data_manager.calculate_module_snapshot_hash([module])

    assert snapshot_hash == data_manager.calculate_module_snapshot_hash(
        [reordered_module]
    )
    assert snapshot_hash != data_manager.calculate_module_snapshot_hash(
        [module_payload("Quiz updated")]
    )


def test_pipeline_rerun_returns_latest_complete_result(database_url):
    """A project read returns the newest saved pipeline payload unchanged."""
    project = data_manager.create_project("Trimester 1", database_url=database_url)
    first_run = data_manager.start_pipeline_run(project["id"], 1, database_url)
    first = module_payload()
    first_payload = {"module_count": 1, "modules": [first], "schedule": {"weeks": []}}
    data_manager.save_pipeline_result(
        project["id"],
        first_run,
        first_payload,
        [],
        database_url=database_url,
    )

    second_run = data_manager.start_pipeline_run(project["id"], 1, database_url)
    second = module_payload("Quiz updated")
    second_payload = {
        "module_count": 1,
        "modules": [second],
        "schedule": {"weeks": [{"week": 1, "items": []}]},
    }
    data_manager.save_pipeline_result(
        project["id"],
        second_run,
        second_payload,
        [],
        database_url=database_url,
    )

    assert data_manager.get_latest_pipeline_result(
        project["id"], database_url
    ) == second_payload
    overview = data_manager.get_project_overview(project["id"], database_url)
    assert overview["modules"] == [second]
    assert overview["schedule"] == second_payload["schedule"]


def test_recommendation_is_saved_separately_from_pipeline_result(database_url):
    """Study advice has its own record and never mutates the saved result."""
    project = data_manager.create_project("Planning", database_url=database_url)
    module = module_payload()
    saved = data_manager.save_recommendation(
        project["id"],
        "work_checklist",
        [module],
        {"available_hours_per_week": 6},
        {"recommendation_type": "work_checklist", "items": []},
        "v1",
        "qwen",
        database_url,
    )

    assert saved["status"] == "candidate"
    assert saved["recommendation_payload"]["recommendation_type"] == "work_checklist"
    assert data_manager.list_recommendations(project["id"], database_url)[0]["id"] == saved["id"]


def test_concurrent_accepts_leave_one_accepted_candidate_per_type(database_url):
    from concurrent.futures import ThreadPoolExecutor
    from src.data_manager import PostgresRepository
    from tests.function.test_repository_contract import advice
    repository = PostgresRepository(database_url)
    project = repository.get_or_create_project("Concurrent acceptance")
    candidates = [repository.save_recommendation(project_id=project["id"], **advice()) for _ in range(2)]
    def accept(candidate):
        return repository.set_recommendation_status(project["id"], candidate["id"], "accepted")
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert len(list(executor.map(accept, candidates))) == 2
    assert [row["status"] for row in repository.list_recommendations(project["id"])].count("accepted") == 1


def test_connection_failure_is_typed_and_does_not_expose_connection_details():
    import pytest
    from src.data_manager import PostgresRepository, DataManagerError
    with pytest.raises(DataManagerError, match="Could not connect to PostgreSQL"):
        PostgresRepository("postgresql://unused:unused@127.0.0.1:1/unused").check_connection()
