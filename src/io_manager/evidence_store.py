"""Run-owned evidence copies with deterministic cleanup."""

from contextlib import AbstractContextManager
from pathlib import Path
import logging
import shutil
import tempfile
import uuid
from PIL import Image, UnidentifiedImageError
from .submission_validator import format_io_error

TMP_DIRECTORY = Path("/tmp/stackplan-intake")
ACCEPTED_IMAGE_FORMATS = {".jpeg": "JPEG", ".jpg": "JPEG", ".png": "PNG"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_LONG_SIDE = 7680
MAX_SHORT_SIDE = 4320
LOGGER = logging.getLogger(__name__)


class EvidenceStore(AbstractContextManager):
    """Own only the staged copies created by this store, never source files."""

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else None
        self._temporary = None
        self._owned = []

    def __enter__(self):
        if self.directory is None:
            self._temporary = tempfile.TemporaryDirectory(prefix="stackplan-intake-")
            self.directory = Path(self._temporary.name)
        return self

    def __exit__(self, *exc):
        try:
            for path in self._owned:
                path.unlink(missing_ok=True)
        finally:
            self._owned.clear()
            if self._temporary is not None:
                self._temporary.cleanup()

    def validate_image(self, image_path):
        """Raise ``ValueError`` unless a path contains a supported, safe image.

        This is the only image-validation boundary. Later managers may trust the
        copied file's format, size, dimensions and readability.
        """
        extension = image_path.suffix.lower()
        if extension not in ACCEPTED_IMAGE_FORMATS:
            accepted = ", ".join(ACCEPTED_IMAGE_FORMATS)
            raise ValueError(
                f"Unsupported image format '{extension or 'none'}'. Accepted formats: {accepted}."
            )
        if image_path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds the 10 MB size limit.")
        try:
            with Image.open(image_path) as image:
                detected_format = image.format
                (width, height) = image.size
                image.verify()
        except (
            OSError,
            SyntaxError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
        ) as error:
            raise ValueError("File is not a readable image.") from error
        if detected_format != ACCEPTED_IMAGE_FORMATS[extension]:
            raise ValueError("Image extension does not match its contents.")
        if width <= 10 or height <= 10:
            raise ValueError("Image width and height must both exceed 10 pixels.")
        if max(width, height) > MAX_LONG_SIDE or min(width, height) > MAX_SHORT_SIDE:
            raise ValueError("Image resolution exceeds the supported 8K limit.")
        if max(width, height) / min(width, height) > 200:
            raise ValueError("Image aspect ratio cannot exceed 200:1.")

    def stage(self, file_paths, base_directory=None):
        """Validate local images and copy accepted files into /tmp.

        The returned path list stays aligned with ``file_paths``. A failed position
        contains ``None`` and its explanation is appended to the returned hard-error
        list. Relative paths are resolved from ``base_directory`` when provided.
        """
        LOGGER.info(
            "Validating and storing %d image(s) in %s", len(file_paths), self.directory
        )
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            stored_paths = [None] * len(file_paths)
            failure = format_io_error(error)
            LOGGER.error("%s", failure)
            return (stored_paths, [failure])
        stored_paths = []
        errors = []
        for position, file_path in enumerate(file_paths):
            destination = None
            if not isinstance(file_path, str):
                stored_paths.append(None)
                errors.append(
                    format_io_error(
                        f"file_path at position {position} must be a string."
                    )
                )
                continue
            try:
                source = Path(file_path).expanduser()
                if base_directory is not None and (not source.is_absolute()):
                    source = Path(base_directory) / source
                self.validate_image(source)
                destination = self.directory / f"{uuid.uuid4().hex}-{source.name}"
                shutil.copyfile(source, destination)
            except (OSError, ValueError) as error:
                if destination is not None:
                    destination.unlink(missing_ok=True)
                stored_paths.append(None)
                failure = format_io_error(f"Could not store image {file_path}: {error}")
                LOGGER.warning("%s", failure)
                errors.append(failure)
                continue
            self._owned.append(destination)
            stored_paths.append(str(destination))
        LOGGER.info(
            "Image storage completed with %d success(es) and %d failure(s)",
            len(stored_paths) - stored_paths.count(None),
            stored_paths.count(None),
        )
        return (stored_paths, errors)
