"""Complete application slices, faking only provider and persistence IO."""

import asyncio
import json
from pathlib import Path

import pytest
from PIL import Image

from src import main
from src.ai_manager import AIManager
from src.application.planning_service import PlanningService
from src.data_manager import DataManager, DataManagerError, PostgresRepository
from src.io_manager import EvidenceStore
from tests.fakes import FakeProvider, MemoryRepository


@pytest.fixture
def submission(tmp_path):
    Image.new("RGB", (20, 20)).save(tmp_path / "quiz.png")
    return {
        "module_count": 2,
        "modules": [
            {"module_title": title, "credit": 6, "file_path": "quiz.png"}
            for title in ("INF1103", "INF1104")
        ],
    }


def service(provider, repository=None, evidence_factory=EvidenceStore):
    return PlanningService(
        ai=AIManager(client_factory=lambda: provider),
        data=DataManager(repository) if repository is not None else None,
        evidence_factory=evidence_factory,
    )


@pytest.mark.parametrize(
    "failed,expected,status",
    [
        ((), 2, "completed"),
        (("INF1103",), 1, "partial"),
        (("INF1103", "INF1104"), 0, "failed"),
    ],
)
def test_success_and_independent_module_failures(
    submission, tmp_path, failed, expected, status
):
    provider = FakeProvider(fail_modules=failed)
    repository = MemoryRepository()
    result = asyncio.run(service(provider, repository).run(submission, tmp_path))
    assert result.status == status
    if expected:
        assert result.payload["module_count"] == expected
        assert result.payload["schedule"]["scheduled_assessment_count"] == expected
        assert "study_plan" in result.payload
        assert repository.get_latest_pipeline_result(1) == result.payload
    else:
        assert result.payload is None
    assert len(result.errors) == len(failed)
    assert provider.closed
    assert repository.list_pipeline_runs(1)[0]["status"] == status


@pytest.mark.parametrize(
    "provider", [FakeProvider(invalid_plan=True), FakeProvider(advice_delay=0.1)]
)
def test_advice_failure_or_timeout_keeps_factual_schedule(
    submission, tmp_path, provider
):
    result = asyncio.run(service(provider).run(submission, tmp_path, timeout=0.05))
    assert result.status == "partial"
    assert result.payload["schedule"]["scheduled_assessment_count"] == 2
    assert "study_plan" not in result.payload
    assert result.errors
    assert provider.closed


def test_storage_failure_does_not_discard_result(submission, tmp_path):
    class FailingRepository(MemoryRepository):
        def complete_run(self, *args, **kwargs):
            raise DataManagerError("connection lost")

    result = asyncio.run(
        service(FakeProvider(), FailingRepository()).run(submission, tmp_path)
    )
    assert result.status == "partial"
    assert result.payload["study_plan"]
    assert result.errors == ("Data Manager error: connection lost",)


def test_start_failure_keeps_the_workflow_usable(submission, tmp_path):
    class FailingRepository(MemoryRepository):
        def get_or_create_project(self, *args, **kwargs):
            raise DataManagerError("offline")

    result = asyncio.run(
        service(FakeProvider(), FailingRepository()).run(submission, tmp_path)
    )
    assert result.payload["module_count"] == 2
    assert result.errors == ("Data Manager error: offline",)


def test_two_concurrent_runs_on_one_service_do_not_share_state(submission, tmp_path):
    provider = FakeProvider(fail_modules=("INF1103",), delay=0.001)
    shared = service(provider)

    async def run_both():
        return await asyncio.gather(
            shared.run(submission, tmp_path),
            shared.run(
                {"module_count": 1, "modules": [submission["modules"][1]]}, tmp_path
            ),
        )

    partial, complete = asyncio.run(run_both())
    assert partial.status == "partial" and complete.status == "completed"
    assert len(partial.errors) == 1 and complete.errors == ()
    altered = complete.payload
    altered["modules"][0]["notes"].append("external mutation")
    assert complete.payload["modules"][0]["notes"] == []


@pytest.mark.parametrize("failure", ["timeout", "unexpected", "no_evidence"])
def test_cleanup_on_all_exit_paths(submission, tmp_path, failure):
    stores = []

    def evidence_factory():
        store = EvidenceStore()
        stores.append(store)
        return store

    class BrokenAI(AIManager):
        async def process_payload(self, *args, **kwargs):
            raise RuntimeError("unexpected defect")

    app = service(
        FakeProvider(delay=0.1 if failure == "timeout" else 0),
        evidence_factory=evidence_factory,
    )
    if failure == "unexpected":
        app.ai = BrokenAI()
    if failure == "no_evidence":
        submission["modules"][0]["file_path"] = "missing.png"
        submission["modules"][1]["file_path"] = "missing.png"
    result = asyncio.run(app.run(submission, tmp_path, timeout=0.02))
    assert result.status == "failed" and result.errors
    assert not stores[0].directory.exists()
    assert (tmp_path / "quiz.png").exists()


def test_cli_uses_shared_workflow_and_prints_json(
    submission, tmp_path, monkeypatch, capsys
):
    manifest = tmp_path / "payload.json"
    manifest.write_text(json.dumps(submission))
    monkeypatch.setattr(main, "create_service", lambda: service(FakeProvider()))
    payload, errors = main.main([str(manifest)])
    assert json.loads(capsys.readouterr().out) == {"payload": payload, "errors": errors}
    assert payload["schedule"]["scheduled_assessment_count"] == 2


def test_pipeline_persists_objects_and_advice_in_postgres(
    submission, tmp_path, database_url
):
    repository = PostgresRepository(database_url)
    result = asyncio.run(service(FakeProvider(), repository).run(submission, tmp_path))
    assert result.status == "completed"
    projects = repository.list_projects()
    assert repository.get_latest_pipeline_result(projects[0]["id"]) == result.payload
    assert (
        repository.list_recommendations(projects[0]["id"])[0]["recommendation_payload"]
        == result.payload["study_plan"]
    )


def test_duplicate_modules_cannot_leave_ambiguous_assessment_references(
    submission, tmp_path
):
    submission["modules"][1]["module_title"] = "INF1103"
    result = asyncio.run(service(FakeProvider()).run(submission, tmp_path))
    assert result.status == "partial" and result.payload["module_count"] == 1
    assert "Duplicate assessment_id" in result.errors[0]
    assert result.payload["study_plan"]
