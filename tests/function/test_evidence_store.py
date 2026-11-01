"""Evidence ownership and partial intake behaviour."""

from pathlib import Path

import pytest
from PIL import Image

from src.io_manager import IOManager, EvidenceStore


@pytest.mark.parametrize("fail", [False, True])
def test_staged_copies_are_removed_on_success_and_failure(tmp_path, fail):
    source = tmp_path / "evidence.png"
    Image.new("RGB", (20, 20)).save(source)
    staged = None
    try:
        with EvidenceStore() as evidence:
            staged, errors = evidence.stage([str(source)])
            assert errors == []
            assert Path(staged[0]).is_file()
            if fail:
                raise RuntimeError("downstream failure")
    except RuntimeError:
        pass
    assert not Path(staged[0]).exists()
    assert source.exists()


@pytest.mark.parametrize("relative", [False, True])
def test_one_invalid_image_preserves_other_evidence(tmp_path, relative):
    source = tmp_path / "evidence.png"
    Image.new("RGB", (20, 20)).save(source)
    path = source.name if relative else str(source)
    with EvidenceStore() as evidence:
        payload, errors = IOManager().accept(
            {
                "module_count": 1,
                "modules": [
                    {
                        "module_title": "INF1103",
                        "credit": 6,
                        "file_paths": [path, "missing.png"],
                    }
                ],
            },
            evidence,
            tmp_path,
        )
        assert payload["module_count"] == 1
        assert len(payload["modules"][0]["stored_file_paths"]) == 1
        assert len(errors) == 1


@pytest.mark.parametrize(
    "filename,content",
    [
        ("bad.txt", b"text"),
        ("bad.png", b"unreadable"),
        ("large.png", b"x" * (10 * 1024 * 1024 + 1)),
    ],
)
def test_no_usable_evidence_returns_failure_without_copies(tmp_path, filename, content):
    source = tmp_path / filename
    source.write_bytes(content)
    with EvidenceStore() as evidence:
        payload, errors = IOManager().accept(
            {
                "module_count": 1,
                "modules": [
                    {"module_title": "INF1103", "credit": 6, "file_path": str(source)}
                ],
            },
            evidence,
        )
        assert payload is None and errors
        assert list(evidence.directory.iterdir()) == []
