"""Procedural input pipeline for local AI file processing.

Flow:
    CLI arguments -> JSON payload -> basic type validation -> temporary copies
    -> clean AI payload.

The public processing functions return ``(data, errors)``. ``data`` contains
only modules that can continue. Errors are kept as consistently formatted
strings so they can be collected without entering the AI payload.
"""

import argparse
import json
import logging
from pathlib import Path
import shutil
import uuid
from PIL import Image, UnidentifiedImageError

TMP_DIRECTORY = Path("/tmp/stackplan-intake")
ACCEPTED_IMAGE_FORMATS = {
    ".jpeg": "JPEG",
    ".jpg": "JPEG",
    ".png": "PNG",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_LONG_SIDE = 7680
MAX_SHORT_SIDE = 4320
LOGGER = logging.getLogger(__name__)


def format_io_error(error):
    """Return one hard IO error using the pipeline's readable prefix."""
    return f"IO Manager error: {error}"


# CLI boundary
def parse_cli_arguments(argv=None):
    """Return the payload-file argument as a plain dictionary.

    ``argv`` is optional so tests can provide arguments without changing the
    real command line.
    """
    parser = argparse.ArgumentParser(
        description="Process a JSON module payload for AI file intake."
    )
    parser.add_argument("payload_file", type=Path, help="Path to the JSON payload.")
    return vars(parser.parse_args(argv))


def load_cli_payload(payload_path):
    """Read a JSON payload file and return ``(payload, errors)``.

    File access and JSON syntax failures stop IO processing and are returned as
    hard errors. Payload structure is checked later by ``validate_payload``.
    """
    LOGGER.info("Loading payload from %s", payload_path)
    try:
        with payload_path.open("r", encoding="utf-8") as payload_stream:
            payload = json.load(payload_stream)
    except (OSError, json.JSONDecodeError) as error:
        # Reading and JSON syntax failures stop intake before validation.
        return None, [format_io_error(error)]
    LOGGER.info("Payload loaded")
    return payload, []


# Payload validation
def validate_payload(payload):
    """Return valid module dictionaries and hard metadata errors.

    Invalid top-level fields stop the payload. Invalid module entries are
    removed individually so the remaining modules can continue.
    """
    if not isinstance(payload, dict):
        error = format_io_error("Payload must be a dictionary.")
        return None, [error]

    module_count = payload.get("module_count")
    modules = payload.get("modules")

    # Invalid top-level structure prevents safe module processing.
    errors = []
    if type(module_count) is not int:
        errors.append(
            format_io_error("module_count must be an integer.")
        )
    if not isinstance(modules, list) or not modules:
        errors.append(
            format_io_error("modules must be a non-empty array.")
        )
        return None, errors
    if type(module_count) is int and module_count != len(modules):
        errors.append(
            format_io_error("module_count must match the number of modules.")
        )
    if errors:
        return None, errors

    # A malformed module is removed without blocking the remaining modules.
    valid_modules = []
    for position, module in enumerate(modules):
        if not isinstance(module, dict):
            errors.append(
                format_io_error(
                    f"Module at position {position} must be a dictionary."
                )
            )
            continue

        module_title = module.get("module_title")
        credit = module.get("credit")
        if not isinstance(module_title, str) or type(credit) is not int:
            errors.append(
                format_io_error(
                    f"Module metadata at position {position} has an invalid type."
                )
            )
            continue

        valid_modules.append(module)
    LOGGER.info(
        "Payload validation accepted %d of %d module(s)",
        len(valid_modules),
        len(modules),
    )
    return valid_modules, errors


# Image validation and temporary storage
def validate_image(image_path):
    """Raise ``ValueError`` unless a path contains a supported, safe image.

    This is the only image-validation boundary. Later managers may trust the
    copied file's format, size, dimensions and readability.
    """
    extension = image_path.suffix.lower()
    if extension not in ACCEPTED_IMAGE_FORMATS:
        accepted = ", ".join(ACCEPTED_IMAGE_FORMATS)
        raise ValueError(
            f"Unsupported image format '{extension or 'none'}'. "
            f"Accepted formats: {accepted}."
        )

    if image_path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 10 MB size limit.")

    try:
        with Image.open(image_path) as image:
            detected_format = image.format
            width, height = image.size
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


def validate_and_store_images(file_paths, base_directory=None):
    """Validate local images and copy accepted files into /tmp.

    The returned path list stays aligned with ``file_paths``. A failed position
    contains ``None`` and its explanation is appended to the returned hard-error
    list. Relative paths are resolved from ``base_directory`` when provided.
    """
    LOGGER.info(
        "Validating and storing %d image(s) in %s",
        len(file_paths),
        TMP_DIRECTORY,
    )
    try:
        TMP_DIRECTORY.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        # No image can be stored when the working directory is unavailable.
        stored_paths = [None] * len(file_paths)
        failure = format_io_error(error)
        LOGGER.error("%s", failure)
        return stored_paths, [failure]

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
            if base_directory is not None and not source.is_absolute():
                source = Path(base_directory) / source

            validate_image(source)

            # The UUID prevents files with identical names from overwriting.
            destination = TMP_DIRECTORY / f"{uuid.uuid4().hex}-{source.name}"
            shutil.copyfile(source, destination)
        except (OSError, ValueError) as error:
            if destination is not None:
                destination.unlink(missing_ok=True)

            # None preserves the failed file's position for module matching.
            stored_paths.append(None)
            failure = format_io_error(
                f"Could not store image {file_path}: {error}"
            )
            LOGGER.warning("%s", failure)
            errors.append(failure)
            continue

        stored_paths.append(str(destination))
    LOGGER.info(
        "Image storage completed with %d success(es) and %d failure(s)",
        len(stored_paths) - stored_paths.count(None),
        stored_paths.count(None),
    )
    return stored_paths, errors


# AI payload preparation
def process_payload(payload, base_directory=None):
    """Return an AI-ready payload and all hard IO errors.

    This function combines the existing metadata and image steps without
    repeating their checks. Modules whose images fail are left out.
    """
    valid_modules, errors = validate_payload(payload)
    if valid_modules is None or not valid_modules:
        return None, errors

    # Keep paths in module order so copied results map back by position.
    file_paths = []
    for module in valid_modules:
        file_paths.append(module.get("file_path"))

    stored_paths, image_errors = validate_and_store_images(
        file_paths,
        base_directory=base_directory,
    )
    errors.extend(image_errors)

    processed_modules = []
    for position, stored_path in enumerate(stored_paths):
        # Failed copies are reported through errors, not sent to the AI manager.
        if stored_path is None:
            continue

        module = valid_modules[position]
        processed_modules.append(
            {
                "module_title": module["module_title"],
                "credit": module["credit"],
                "stored_file_path": stored_path,
            }
        )

    if not processed_modules:
        # No usable module means later pipeline stages have nothing to process.
        return None, errors

    ai_payload = {
        "module_count": len(processed_modules),
        "modules": processed_modules,
    }
    LOGGER.info("AI payload prepared with %d module(s)", len(processed_modules))
    return ai_payload, errors


# Complete IO-manager entry point
def process_cli_input(cli_input):
    """Load the CLI payload and return IO Manager's final ``(payload, errors)``.

    The payload file's directory becomes the base for relative image paths.
    """
    # argparse already guarantees payload_file is a Path object.
    payload_path = cli_input["payload_file"].expanduser().resolve()
    LOGGER.info("IO Manager started for %s", payload_path)
    payload, errors = load_cli_payload(payload_path)
    if errors:
        return None, errors

    # Relative image paths are interpreted from the JSON file's directory.
    return process_payload(payload, base_directory=payload_path.parent)
