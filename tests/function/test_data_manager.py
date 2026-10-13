"""Function tests for PostgreSQL persistence and current-result selection."""

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


def test_pipeline_rerun_returns_latest_module_result(database_url):
    """A project read returns the newest stored result for each module."""
    project = data_manager.create_project("Trimester 1", database_url=database_url)
    first_run = data_manager.start_pipeline_run(project["id"], 1, database_url)
    first = module_payload()
    data_manager.save_pipeline_result(
        project["id"],
        first_run,
        {"module_count": 1, "modules": [first], "schedule": {}},
        [],
        source_hashes={"INF1104": "hash-one"},
        prompt_version="v1",
        model_name="qwen",
        database_url=database_url,
    )

    second_run = data_manager.start_pipeline_run(project["id"], 1, database_url)
    second = module_payload("Quiz updated")
    data_manager.save_pipeline_result(
        project["id"],
        second_run,
        {"module_count": 1, "modules": [second], "schedule": {}},
        [],
        source_hashes={"INF1104": "hash-two"},
        prompt_version="v1",
        model_name="qwen",
        database_url=database_url,
    )

    assert data_manager.get_current_modules(project["id"], database_url) == [second]
    assert "module_revisions" not in data_manager.get_project_overview(
        project["id"], database_url
    )


def test_recommendation_is_saved_separately_from_module_facts(database_url):
    """Study advice has its own record and never mutates current modules."""
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
