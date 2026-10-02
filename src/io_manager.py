"""Validate and classify frontend data before AI processing."""

from pathlib import Path


IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
DOCUMENT_TYPES = {
    ".txt": "text",
    ".md": "text",
    ".csv": "text",
    ".json": "text",
    ".pdf": "pdf",
    ".docx": "docx",
}

#Validation Helpers
def validate_module_count(module_count):
    """Check that the frontend declared at least one module."""
    if type(module_count) is not int or module_count < 1:
        return ["Module count must be a positive integer."]
    return []


def validate_data_payload(data_payload):
    """Check that the payload contains a non-empty modules list."""
    if not isinstance(data_payload, dict):
        return ["Data payload must be an object."]

    modules = data_payload.get("modules")
    if not isinstance(modules, list) or not modules:
        return ["Data payload must contain at least one module."]
    return []


def validate_payload_module_count(module_count, data_payload):
    """Check that the declared count matches the supplied modules."""
    modules = data_payload["modules"]
    if len(modules) != module_count:
        return ["Module count does not match the data payload."]
    return []


def validate_module_objects(data_payload):
    """Check that every module uses the expected object structure."""
    modules = data_payload["modules"]
    for module_index, module in enumerate(modules, start=1):
        if not isinstance(module, dict):
            return [f"Module {module_index} must be an object."]
    return []


def validate_module_names(data_payload):
    """Check that every module has a readable name or code."""
    errors = []
    modules = data_payload["modules"]
    for module_index, module in enumerate(modules, start=1):
        module_name = module.get("module_name")
        if not isinstance(module_name, str) or not module_name.strip():
            errors.append(f"Module {module_index} requires a module name.")
    return errors


def validate_credit_units(data_payload):
    """Check that supplied credit values are positive numbers."""
    errors = []
    modules = data_payload["modules"]
    for module_index, module in enumerate(modules, start=1):
        credit_units = module.get("credit_units")
        credit_is_number = type(credit_units) in (int, float)
        if credit_units is not None and not credit_is_number:
            errors.append(f"Module {module_index} credit units must be a number.")
        if credit_is_number and credit_units <= 0:
            errors.append(f"Module {module_index} credit units must be positive.")
    return errors


def validate_file_lists(data_payload):
    """Check that every module supplies its file paths as a list."""
    errors = []
    modules = data_payload["modules"]
    for module_index, module in enumerate(modules, start=1):
        file_paths = module.get("files")
        if not isinstance(file_paths, list):
            errors.append(f"Module {module_index} files must be a list.")
    return errors


def validate_file_path_values(data_payload):
    """Check that every supplied file path is a non-empty string."""
    errors = []
    modules = data_payload["modules"]
    for module_index, module in enumerate(modules, start=1):
        for file_index, file_path in enumerate(module["files"], start=1):
            if not isinstance(file_path, str) or not file_path.strip():
                errors.append(
                    f"Module {module_index} file {file_index} must be a readable path."
                )
    return errors


def validate_file_types(data_payload):
    """Check that every path has one supported image or document extension."""
    errors = []
    supported_types = set(IMAGE_MEDIA_TYPES) | set(DOCUMENT_TYPES)
    modules = data_payload["modules"]
    for module_index, module in enumerate(modules, start=1):
        for file_path in module["files"]:
            file_extension = Path(file_path).suffix.lower()
            if file_extension not in supported_types:
                errors.append(
                    f"Module {module_index} contains unsupported file type "
                    f"{file_extension or '[no extension]'}."
                )
    return errors


def validate_repeating_schedule_data(repeating_schedule_data):
    """Check that optional retry schedule data uses an object structure."""
    if repeating_schedule_data is None:
        return []
    if not isinstance(repeating_schedule_data, dict):
        return ["Repeating schedule data must be an object or null."]
    return []


def validate_calendar(data_payload):
    """Check that optional recess weeks are positive week numbers."""
    calendar = data_payload.get("calendar")
    if calendar is None:
        return []
    if not isinstance(calendar, dict):
        return ["Calendar must be an object."]

    recess_weeks = calendar.get("recess_weeks", [])
    if not isinstance(recess_weeks, list):
        return ["Calendar recess weeks must be a list."]

    errors = []
    for recess_week in recess_weeks:
        week_is_valid = type(recess_week) is int and 0 < recess_week <= 30
        if not week_is_valid:
            errors.append("Each recess week must be an integer between 1 and 30.")
    return errors


#Validation function that wraps all Validation Helpers
def validate_input(module_count, data_payload, repeating_schedule_data=None):
    """Run the complete validation flow and return its collected errors."""
    errors = []

    # Validate the top-level input before reading module contents.
    module_count_errors = validate_module_count(module_count)
    errors.extend(module_count_errors)

    data_payload_errors = validate_data_payload(data_payload)
    errors.extend(data_payload_errors)

    if errors:
        # Nested validation is unsafe when the top-level structure is invalid.
        return errors

    # Validate the repeated module structure before reading module fields.
    payload_count_errors = validate_payload_module_count(module_count, data_payload)
    errors.extend(payload_count_errors)

    module_object_errors = validate_module_objects(data_payload)
    errors.extend(module_object_errors)

    if errors:
        # Field validation requires the count and module objects to be valid.
        return errors

    # Validate each logical field and the optional retry data.
    module_name_errors = validate_module_names(data_payload)
    errors.extend(module_name_errors)

    credit_unit_errors = validate_credit_units(data_payload)
    errors.extend(credit_unit_errors)

    file_list_errors = validate_file_lists(data_payload)
    errors.extend(file_list_errors)

    if file_list_errors:
        return errors

    file_path_errors = validate_file_path_values(data_payload)
    errors.extend(file_path_errors)

    if file_path_errors:
        return errors

    file_type_errors = validate_file_types(data_payload)
    errors.extend(file_type_errors)

    calendar_errors = validate_calendar(data_payload)
    errors.extend(calendar_errors)

    schedule_errors = validate_repeating_schedule_data(repeating_schedule_data)
    errors.extend(schedule_errors)

    # Return every logical input error to the caller in one result.
    return errors


#AI Manager Hand Off
def prepare_ai_input(module_count, data_payload, repeating_schedule_data=None):
    """Return validated frontend data in the shape expected by the AI manager."""
    errors = validate_input(
        module_count,
        data_payload,
        repeating_schedule_data,
    )
    if errors:
        # Invalid frontend data stops before the AI manager is called.
        return None, errors

    prepared_modules = []
    for module in data_payload["modules"]:
        images = []
        documents = []
        image_number = 0
        for file_path in module["files"]:
            file_extension = Path(file_path).suffix.lower()
            if file_extension in IMAGE_MEDIA_TYPES:
                image_number += 1
                image = {
                    "source_id": f"image_{image_number}",
                    "path": file_path,
                    "media_type": IMAGE_MEDIA_TYPES[file_extension],
                }
                images.append(image)
            else:
                document = {
                    "path": file_path,
                    "document_type": DOCUMENT_TYPES[file_extension],
                }
                documents.append(document)

        prepared_module = {
            "module_name": module["module_name"],
            "credit_units": module.get("credit_units"),
            "additional_context": module.get("additional_context", ""),
            "images": images,
            "documents": documents,
        }
        prepared_modules.append(prepared_module)

    calendar = data_payload.get("calendar")
    if calendar is None:
        calendar = {"recess_weeks": []}

    ai_input = {
        "module_count": module_count,
        "modules": prepared_modules,
        "calendar": calendar,
        "repeating_schedule_data": repeating_schedule_data,
    }
    return ai_input, []
