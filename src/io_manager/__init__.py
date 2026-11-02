"""Legacy intake adapters; application code uses IOManager and run-owned stores."""

import argparse
import json
import logging
from pathlib import Path
from .manager import IOManager
from .submission_validator import SubmissionValidator, format_io_error
from .evidence_store import (
    EvidenceStore,
    TMP_DIRECTORY,
    ACCEPTED_IMAGE_FORMATS,
    MAX_IMAGE_BYTES,
    MAX_LONG_SIDE,
    MAX_SHORT_SIDE,
)
from .result_presenter import ResultPresenter

LOGGER = logging.getLogger(__name__)


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


def validate_payload(payload):
    return SubmissionValidator().validate(payload)


def validate_image(image_path):
    return EvidenceStore().validate_image(image_path)


def validate_and_store_images(file_paths, base_directory=None):
    return EvidenceStore(TMP_DIRECTORY).stage(file_paths, base_directory)


def process_payload(payload, base_directory=None):
    return IOManager().accept(payload, EvidenceStore(TMP_DIRECTORY), base_directory)


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


def display_pipeline_result(payload, errors):
    ResultPresenter().display(payload, errors)


def display_message(message, error=False, end="\n"):
    ResultPresenter().message(message, error, end)
