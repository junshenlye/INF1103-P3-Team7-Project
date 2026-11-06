"""Contract tests for the frontend-facing API helper."""

import io
import json
from pathlib import Path
from types import SimpleNamespace

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
        api_helper.logic_manager,
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

    def fake_run(command, **_kwargs):
        captured.update(json.loads(Path(command[-1]).read_text(encoding="utf-8")))
        return SimpleNamespace(
            stdout=json.dumps({"payload": {"modules": []}, "errors": []}),
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(api_helper.subprocess, "run", fake_run)
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

    def fake_run(command, **_kwargs):
        manifest_path = Path(command[-1])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for module in manifest["modules"]:
            evidence_path = manifest_path.parent / module["file_paths"][0]
            captured.append(
                (module["module_title"], evidence_path.read_bytes())
            )
        return SimpleNamespace(
            stdout=json.dumps({"payload": {"modules": []}, "errors": []}),
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(api_helper.subprocess, "run", fake_run)
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

    assert client.post(
        "/api/projects/1/modules/INF1103/confirm",
        json={"revision": 1},
    ).status_code == 404
    assert client.put(
        "/api/projects/1/modules/INF1103",
        json={"module_title": "INF1103"},
    ).status_code == 404
    assert client.get("/api/projects/1/schedule").status_code == 404
