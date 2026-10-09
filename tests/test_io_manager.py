"""Tests for image intake and temporary storage."""

from PIL import Image

from src import io_manager


def test_stored_images_are_lossless_pngs(tmp_path, monkeypatch):
    temporary_directory = tmp_path / "intake"
    monkeypatch.setattr(io_manager, "TMP_DIRECTORY", temporary_directory)

    for extension, image_format in ((".png", "PNG"), (".jpg", "JPEG")):
        source = tmp_path / f"source{extension}"
        original = Image.new("RGB", (24, 16), (25, 100, 220))
        original.save(source, format=image_format)

        stored_paths, errors = io_manager.validate_and_store_images([str(source)])

        assert errors == []
        assert len(stored_paths) == 1
        stored_path = stored_paths[0]
        assert stored_path.endswith(".png")

        with Image.open(source) as source_image:
            expected_pixels = source_image.convert("RGB").tobytes()
        with Image.open(stored_path) as stored_image:
            assert stored_image.format == "PNG"
            assert stored_image.convert("RGB").tobytes() == expected_pixels
