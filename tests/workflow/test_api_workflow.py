"""Contract tests for the frontend-facing API helper."""

import io
import json

import pytest
from pathlib import Path
from types import SimpleNamespace

from src import logic_manager
from src.application.pipeline_result import PipelineResult

from helpers import api_helper


def test_project_api_returns_independent_json_contract(monkeypatch):
    """The frontend receives JSON without importing backend implementation."""
    monkeypatch.setattr(
        api_helper.data_manager,
        "list_projects",
        lambda: [{"id": 1, "name": "Trimester 1", "week_count": 14}],
    )
    client = api_helper.APP.test_client()

    response = client.get("/api/projects")

    assert response.status_code == 200
    assert response.get_json() == {
        "payload": [{"id": 1, "name": "Trimester 1", "week_count": 14}],
        "errors": [],
    }


def test_project_detail_returns_saved_schedule_without_rebuilding(monkeypatch):
    """Loading a project must not send saved modules through Logic Manager."""
    saved_schedule = {"week_count": 14, "weeks": [], "unscheduled": []}
    monkeypatch.setattr(
        api_helper.data_manager,
        "get_project_overview",
        lambda project_id: {
            "id": project_id,
            "modules": [{"module_title": "INF1103"}],
            "schedule": saved_schedule,
            "pipeline_runs": [],
            "recommendations": [],
        },
    )
    monkeypatch.setattr(
        logic_manager,
        "build_weekly_schedule",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("retrieval must not rebuild the schedule")
        ),
    )

    response = api_helper.APP.test_client().get("/api/projects/1")

    assert response.status_code == 200
    assert response.get_json()["payload"]["schedule"] == saved_schedule


def test_process_api_groups_multiple_images_into_one_module(monkeypatch):
    """The helper writes one manifest module with all uploaded evidence."""
    captured = {}
    monkeypatch.setattr(
        api_helper.data_manager,
        "get_project",
        lambda project_id: {"id": project_id},
    )

    async def fake_run(submission, directory, **_kwargs):
        captured.update(submission)
        return PipelineResult({"modules": []}, ())

    monkeypatch.setitem(
        api_helper.APP.config,
        "PLANNING_SERVICE_FACTORY",
        lambda: SimpleNamespace(run=fake_run),
    )
    client = api_helper.APP.test_client()
    modules = [
        {
            "module_title": "INF1102",
            "credit": 6,
            "file_fields": ["schedule", "weights"],
        }
    ]

    response = client.post(
        "/api/projects/1/process",
        data={
            "modules": json.dumps(modules),
            "schedule": (io.BytesIO(b"schedule"), "schedule.png"),
            "weights": (io.BytesIO(b"weights"), "weights.png"),
        },
    )

    assert response.status_code == 200
    assert captured["module_count"] == 1
    assert len(captured["modules"][0]["file_paths"]) == 2


def test_process_api_keeps_each_upload_with_its_module(monkeypatch):
    """Multipart field ordering cannot move INF1103 evidence into INF1102."""
    captured = []
    monkeypatch.setattr(
        api_helper.data_manager,
        "get_project",
        lambda project_id: {"id": project_id},
    )

    async def fake_run(submission, directory, **_kwargs):
        for module in submission["modules"]:
            evidence_path = directory / module["file_paths"][0]
            captured.append((module["module_title"], evidence_path.read_bytes()))
        return PipelineResult({"modules": []}, ())

    monkeypatch.setitem(
        api_helper.APP.config,
        "PLANNING_SERVICE_FACTORY",
        lambda: SimpleNamespace(run=fake_run),
    )
    client = api_helper.APP.test_client()
    modules = [
        {
            "module_title": "INF1102",
            "credit": 6,
            "file_fields": ["inf1102-file"],
        },
        {
            "module_title": "INF1103",
            "credit": 6,
            "file_fields": ["inf1103-file"],
        },
    ]

    response = client.post(
        "/api/projects/1/process",
        data={
            "modules": json.dumps(modules),
            # Deliberately submit the file fields in the opposite order.
            "inf1103-file": (io.BytesIO(b"INF1103 evidence"), "1103.png"),
            "inf1102-file": (io.BytesIO(b"INF1102 evidence"), "1102.png"),
        },
    )

    assert response.status_code == 200
    assert captured == [
        ("INF1102", b"INF1102 evidence"),
        ("INF1103", b"INF1103 evidence"),
    ]


def test_unused_module_revision_routes_are_removed():
    """The API no longer exposes confirmation or manual revision editing."""
    client = api_helper.APP.test_client()

    assert (
        client.post(
            "/api/projects/1/modules/INF1103/confirm",
            json={"revision": 1},
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/api/projects/1/modules/INF1103",
            json={"module_title": "INF1103"},
        ).status_code
        == 404
    )
    assert client.get("/api/projects/1/schedule").status_code == 404


def test_process_http_runs_real_workflow_and_cleans_uploads(monkeypatch):
    from PIL import Image
    from src.ai_manager import AIManager
    from src.application.planning_service import PlanningService
    from tests.fakes import FakeProvider

    provider = FakeProvider(invalid_plan=True)
    monkeypatch.setattr(api_helper.data_manager, "get_project", lambda _: {"id": 1})
    monkeypatch.setitem(
        api_helper.APP.config,
        "PLANNING_SERVICE_FACTORY",
        lambda: PlanningService(ai=AIManager(lambda: provider)),
    )
    source = io.BytesIO()
    Image.new("RGB", (20, 20)).save(source, format="PNG")
    source.seek(0)
    response = api_helper.APP.test_client().post(
        "/api/projects/1/process",
        data={
            "modules": json.dumps(
                [{"module_title": "INF1103", "credit": 6, "file_field": "image"}]
            ),
            "image": (source, "quiz.png"),
        },
    )
    result = response.get_json()
    assert response.status_code == 200
    assert result["payload"]["schedule"]["scheduled_assessment_count"] == 1
    assert "unknown assessment" in result["errors"][0]
    assert provider.closed


def test_http_pipeline_timeout_is_controlled_and_staging_is_removed(monkeypatch):
    from PIL import Image
    from src.ai_manager import AIManager
    from src.application.planning_service import PlanningService
    from src.io_manager import EvidenceStore
    from tests.fakes import FakeProvider

    stores = []

    def factory():
        store = EvidenceStore()
        stores.append(store)
        return store

    monkeypatch.setattr(api_helper.data_manager, "get_project", lambda _: {"id": 1})
    monkeypatch.setenv("PIPELINE_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setitem(
        api_helper.APP.config,
        "PLANNING_SERVICE_FACTORY",
        lambda: PlanningService(
            ai=AIManager(lambda: FakeProvider(delay=0.1)), evidence_factory=factory
        ),
    )
    source = io.BytesIO()
    Image.new("RGB", (20, 20)).save(source, format="PNG")
    source.seek(0)
    response = api_helper.APP.test_client().post(
        "/api/projects/1/process",
        data={
            "modules": json.dumps(
                [{"module_title": "INF1103", "credit": 6, "file_field": "image"}]
            ),
            "image": (source, "quiz.png"),
        },
    )
    assert response.status_code == 422
    assert "timed out" in response.get_json()["errors"][0]
    assert not stores[0].directory.exists()


@pytest.mark.parametrize(
    "form,expected",
    [
        ({"modules": "invalid"}, "valid JSON"),
        ({"modules": "{}"}, "non-empty array"),
        ({"modules": "[null]"}, "invalid"),
        ({"modules": '[{"file_fields": [null]}]'}, "invalid file fields"),
        ({"modules": '[{"file_field": "missing"}]'}, "missing uploaded evidence"),
    ],
)
def test_invalid_http_uploads_return_consistent_errors(monkeypatch, form, expected):
    monkeypatch.setattr(api_helper.data_manager, "get_project", lambda _: {"id": 1})
    response = api_helper.APP.test_client().post("/api/projects/1/process", data=form)
    assert response.status_code == 400
    assert response.get_json()["payload"] is None
    assert expected in response.get_json()["errors"][0]


@pytest.mark.parametrize(
    "method,path,body,status",
    [
        ("post", "/api/projects", [1], 400),
        ("post", "/api/projects/1/recommendations", [1], 400),
        ("post", "/api/projects/1/recommendations/1/status", [1], 400),
    ],
)
def test_nonobject_request_bodies_are_controlled(method, path, body, status):
    response = getattr(api_helper.APP.test_client(), method)(path, json=body)
    assert response.status_code == status
    assert response.get_json()["payload"] is None


def test_framework_and_unexpected_failures_preserve_json_contract(monkeypatch):
    from src.data_manager import DataManagerError

    client = api_helper.APP.test_client()
    assert client.get("/unknown").get_json()["payload"] is None
    monkeypatch.setattr(
        api_helper.data_manager,
        "list_projects",
        lambda: (_ for _ in ()).throw(RuntimeError("secret diagnostic")),
    )
    response = client.get("/api/projects")
    assert response.status_code == 500
    assert response.get_json() == {
        "payload": None,
        "errors": ["Unexpected application failure."],
    }
    monkeypatch.setattr(
        api_helper.data_manager,
        "check_connection",
        lambda: (_ for _ in ()).throw(DataManagerError("offline")),
    )
    response = client.get("/health")
    assert response.status_code == 503 and response.get_json()["errors"] == [
        "Data Manager error: offline"
    ]


def test_http_processing_and_both_advice_types_survive_postgres_reload(
    database_url, monkeypatch
):
    from PIL import Image
    from src.ai_manager import AIManager
    from src.application.planning_service import PlanningService
    from src.data_manager import DataManager, PostgresRepository
    from tests.fakes import FakeProvider

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setitem(
        api_helper.APP.config,
        "PLANNING_SERVICE_FACTORY",
        lambda: PlanningService(
            ai=AIManager(lambda: FakeProvider()),
            data=DataManager(PostgresRepository(database_url)),
        ),
    )
    client = api_helper.APP.test_client()
    created = client.post("/api/projects", json={"name": "HTTP round trip"})
    assert created.status_code == 201
    project_id = created.get_json()["payload"]["id"]
    source = io.BytesIO()
    Image.new("RGB", (20, 20)).save(source, format="PNG")
    source.seek(0)
    processed = client.post(
        f"/api/projects/{project_id}/process",
        data={
            "modules": json.dumps(
                [{"module_title": "INF1103", "credit": 6, "file_field": "image"}]
            ),
            "image": (source, "quiz.png"),
        },
    )
    assert processed.status_code == 200 and processed.get_json()["errors"] == []
    loaded = client.get(f"/api/projects/{project_id}").get_json()["payload"]
    assert loaded["schedule"] == processed.get_json()["payload"]["schedule"]
    assert loaded["pipeline_runs"][0]["status"] == "completed"
    assert (
        loaded["recommendations"][0]["recommendation_payload"]["recommendation_type"]
        == "trimester_revision_plan"
    )
    for kind in ("work_checklist", "trimester_revision_plan"):
        response = client.post(
            f"/api/projects/{project_id}/recommendations",
            json={"recommendation_type": kind},
        )
        assert response.status_code == 201 and response.get_json()["errors"] == []
        recommendation = response.get_json()["payload"]
        accepted = client.post(
            f"/api/projects/{project_id}/recommendations/{recommendation['id']}/status",
            json={"status": "accepted"},
        )
        assert accepted.status_code == 200
        assert accepted.get_json()["payload"]["status"] == "accepted"
    stored = client.get(f"/api/projects/{project_id}/recommendations")
    assert stored.status_code == 200 and len(stored.get_json()["payload"]) == 3
    invalid = client.post(
        f"/api/projects/{project_id}/recommendations", json={"recommendation_type": []}
    )
    assert invalid.status_code == 422
    invalid = client.post(
        f"/api/projects/{project_id}/recommendations",
        json={
            "recommendation_type": "work_checklist",
            "preferences": {"available_hours_per_week": 0},
        },
    )
    assert invalid.status_code == 400
