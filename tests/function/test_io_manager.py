"""Function tests for IO validation and image staging."""

from pathlib import Path

from PIL import Image

from src import io_manager


def test_validate_payload_removes_only_invalid_modules():
    """Valid modules continue while malformed module metadata becomes an error."""
    modules, errors = io_manager.validate_payload(
        {
            "module_count": 2,
            "modules": [
                {"module_title": "INF1104", "credit": 4, "file_path": "a.png"},
                {"module_title": "INF1103", "credit": "4", "file_path": "b.png"},
            ],
        }
    )

    assert modules == [
        {"module_title": "INF1104", "credit": 4, "file_path": "a.png"}
    ]
    assert errors == [
        "IO Manager error: Module metadata at position 1 has an invalid type."
    ]


def test_process_payload_accepts_a_relative_valid_image(tmp_path, monkeypatch):
    """A valid relative PNG becomes an AI-ready stored-file payload."""
    image_path = tmp_path / "module.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    intake = tmp_path / "intake"
    monkeypatch.setattr(io_manager, "TMP_DIRECTORY", intake)

    payload, errors = io_manager.process_payload(
        {
            "module_count": 1,
            "modules": [
                {
                    "module_title": "INF1104",
                    "credit": 4,
                    "file_path": "module.png",
                }
            ],
        },
        base_directory=tmp_path,
    )

    assert errors == []
    assert payload["module_count"] == 1
    assert payload["modules"][0]["module_title"] == "INF1104"
    assert payload["modules"][0]["stored_file_path"].startswith(str(intake))


def test_process_payload_keeps_multiple_images_with_one_module(tmp_path, monkeypatch):
    """Separate schedule and weight pages remain one AI module input."""
    for name in ("schedule.png", "weights.png"):
        Image.new("RGB", (100, 100), "white").save(tmp_path / name)
    intake = tmp_path / "intake"
    monkeypatch.setattr(io_manager, "TMP_DIRECTORY", intake)

    payload, errors = io_manager.process_payload(
        {
            "module_count": 1,
            "modules": [
                {
                    "module_title": "INF1102",
                    "credit": 6,
                    "file_paths": ["schedule.png", "weights.png"],
                }
            ],
        },
        base_directory=tmp_path,
    )

    assert errors == []
    module = payload["modules"][0]
    assert len(module["stored_file_paths"]) == 2
    assert module["stored_file_path"] == module["stored_file_paths"][0]
    assert all(Path(path).parent == intake for path in module["stored_file_paths"])
