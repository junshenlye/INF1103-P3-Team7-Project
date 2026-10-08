"""Procedural input pipeline for local AI file processing.

Flow:
    CLI arguments -> JSON payload -> basic type validation -> temporary copies
    -> clean AI payload.

The public processing functions return ``(data, errors)``. ``data`` contains
only modules with successfully copied files. Recoverable failures are appended
to the separate ``errors`` list and are never placed in the AI payload.
"""

import argparse
import json
from pathlib import Path
import shutil
import uuid

TMP_DIRECTORY = Path("/tmp/stackplan-intake")


def parse_cli_arguments(argv=None):
    """Parse terminal arguments into a plain dictionary."""
    parser = argparse.ArgumentParser(
        description="Process a JSON module payload for AI file intake."
    )
    parser.add_argument("payload_file", type=Path, help="Path to the JSON payload.")
    return vars(parser.parse_args(argv))
    

def load_cli_payload(payload_path):
    """Read one JSON payload file supplied by the CLI."""
    try:
        with payload_path.open("r", encoding="utf-8") as payload_stream:
            payload = json.load(payload_stream)
    except (OSError, json.JSONDecodeError) as error:
        return None, [f"Could not read the JSON payload: {error}"]
    return payload, []


def validate_payload(payload):
    """Check the payload container and basic module field types."""
    if not isinstance(payload, dict):
        return ["CLI payload must be a dictionary."]

    errors = []
    module_count = payload.get("module_count")
    modules = payload.get("modules")

    if type(module_count) is not int:
        errors.append("module_count must be an integer.")
    if not isinstance(modules, list) or not modules:
        errors.append("modules must be a non-empty array.")
        return errors
    if type(module_count) is int and module_count != len(modules):
        errors.append("module_count must match the number of modules.")

    for position, module in enumerate(modules):
        if not isinstance(module, dict):
            errors.append(f"Module at position {position} must be a dictionary.")
            continue

        module_title = module.get("module_title")
        credit = module.get("credit")
        if not isinstance(module_title, str):
            errors.append(f"module_title at position {position} must be a string.")
        if type(credit) is not int:
            errors.append(f"credit at position {position} must be an integer.")
    return errors


def copy_to_tmp(file_paths, base_directory=None):
    """Validate local path strings and copy available files into /tmp.

    The returned path list stays aligned with ``file_paths``. A failed position
    contains ``None`` and its explanation is appended to the error list.
    """
    try:
        TMP_DIRECTORY.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        stored_paths = [None] * len(file_paths)
        return stored_paths, [f"Temporary storage is unavailable: {error}"]

    stored_paths = []
    errors = []
    for position, file_path in enumerate(file_paths):
        destination = None
        try:
            if not isinstance(file_path, str):
                raise TypeError("file_path must be a string")

            source = Path(file_path).expanduser()
            if base_directory is not None and not source.is_absolute():
                source = Path(base_directory) / source
            if not source.is_file():
                raise FileNotFoundError(f"Source file is not available: {source}")
            destination = TMP_DIRECTORY / f"{uuid.uuid4().hex}-{source.name}"
            shutil.copyfile(source, destination)
        except (OSError, TypeError, ValueError) as error:
            if destination is not None:
                destination.unlink(missing_ok=True)
            stored_paths.append(None)
            errors.append(
                f"File at position {position} could not be copied: {error}"
            )
            continue

        stored_paths.append(str(destination))
    return stored_paths, errors


def process_payload(payload, base_directory=None):
    """Validate module data and prepare a clean payload for the AI manager."""
    validation_errors = validate_payload(payload)
    if validation_errors:
        return None, validation_errors

    file_paths = []
    for module in payload["modules"]:
        file_paths.append(module.get("file_path"))

    stored_paths, errors = copy_to_tmp(
        file_paths,
        base_directory=base_directory,
    )

    processed_modules = []
    for position, stored_path in enumerate(stored_paths):
        if stored_path is None:
            continue

        module = payload["modules"][position]
        processed_modules.append(
            {
                "module_title": module["module_title"],
                "credit": module["credit"],
                "stored_file_path": stored_path,
            }
        )

    if not processed_modules:
        return None, errors

    ai_payload = {
        "module_count": len(processed_modules),
        "modules": processed_modules,
    }
    return ai_payload, errors


def process_cli_input(cli_input):
    """Run the complete IO flow for parsed terminal input."""
    payload_path = Path(cli_input["payload_file"]).expanduser().resolve()
    payload, errors = load_cli_payload(payload_path)
    if errors:
        return None, errors
    return process_payload(payload, base_directory=payload_path.parent)
