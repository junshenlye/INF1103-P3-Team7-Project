"""Run the same save/load/transaction/status contract against memory and PostgreSQL."""

import pytest

from src.data_manager import DataManagerError


def payload(title="legacy"):
    return {
        "module_count": 1,
        "modules": [{"module_title": title}],
        "schedule": {"weeks": [], "unscheduled": []},
        "legacy_unknown": None,
    }


def advice(kind="work_checklist"):
    return {
        "recommendation_type": kind,
        "modules": [],
        "preferences": {},
        "recommendation": {"recommendation_type": kind, "items": [], "unknown": None},
        "prompt_version": "contract-v1",
        "model_name": "fake",
    }


@pytest.mark.parametrize("errors", [[], ["AI Manager error: partial extraction"]])
def test_completed_and_partial_legacy_payloads_survive_reload(repository, errors):
    project = repository.get_or_create_project("Contract")
    run = repository.start_pipeline_run(project["id"], 1)
    expected = payload()
    repository.complete_run(project["id"], run, expected, errors)
    expected["modules"].clear()
    assert repository.get_latest_pipeline_result(project["id"]) == payload()
    assert repository.list_pipeline_runs(project["id"])[0]["status"] == (
        "partial" if errors else "completed"
    )


def test_failed_and_running_runs_do_not_hide_newest_usable_result(repository):
    project = repository.get_or_create_project("Latest")
    for document in (payload("old"), payload("new"), None):
        run = repository.start_pipeline_run(project["id"], 1)
        repository.complete_run(
            project["id"], run, document, ["failed"] if document is None else []
        )
    repository.start_pipeline_run(project["id"], 1)
    assert repository.get_latest_pipeline_result(project["id"]) == payload("new")


def test_failure_in_advice_save_rolls_back_result_update(repository):
    project = repository.get_or_create_project("Rollback")
    run = repository.start_pipeline_run(project["id"], 1)
    with pytest.raises(DataManagerError):
        repository.complete_run(
            project["id"], run, payload(), [], advice("unsupported")
        )
    assert repository.list_pipeline_runs(project["id"])[0]["status"] == "running"
    assert repository.get_latest_pipeline_result(project["id"]) is None
    assert repository.list_recommendations(project["id"]) == []


def test_accept_replaces_same_type_only_and_checks_project_ownership(repository):
    project = repository.get_or_create_project("Advice")
    other_project = repository.get_or_create_project("Other")
    first = repository.save_recommendation(project_id=project["id"], **advice())
    revision = repository.save_recommendation(
        project_id=project["id"], **advice("trimester_revision_plan")
    )
    second = repository.save_recommendation(project_id=project["id"], **advice())
    repository.set_recommendation_status(project["id"], first["id"], "accepted")
    repository.set_recommendation_status(project["id"], revision["id"], "accepted")
    repository.set_recommendation_status(project["id"], second["id"], "accepted")
    statuses = {
        row["id"]: row["status"]
        for row in repository.list_recommendations(project["id"])
    }
    assert statuses == {
        first["id"]: "dismissed",
        second["id"]: "accepted",
        revision["id"]: "accepted",
    }
    with pytest.raises(DataManagerError):
        repository.set_recommendation_status(
            other_project["id"], second["id"], "accepted"
        )
    assert (
        repository.set_recommendation_status(project["id"], second["id"], "dismissed")[
            "status"
        ]
        == "dismissed"
    )


def test_result_cannot_be_saved_to_another_projects_run(repository):
    project = repository.get_or_create_project("Owner")
    other = repository.get_or_create_project("Other owner")
    run = repository.start_pipeline_run(project["id"], 1)
    with pytest.raises(DataManagerError):
        repository.complete_run(other["id"], run, payload(), [])
    assert repository.list_pipeline_runs(project["id"])[0]["status"] == "running"
