"""Validate frontend data before it is passed to the AI manager."""


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


def validate_image_paths(data_payload):
    """Check that every module supplies its image paths as a list."""
    errors = []
    modules = data_payload["modules"]
    for module_index, module in enumerate(modules, start=1):
        image_paths = module.get("files")
        if not isinstance(image_paths, list):
            errors.append(f"Module {module_index} files must be a list.")
    return errors


def validate_repeating_schedule_data(repeating_schedule_data):
    """Check that optional retry schedule data uses an object structure."""
    if repeating_schedule_data is None:
        return []
    if not isinstance(repeating_schedule_data, dict):
        return ["Repeating schedule data must be an object or null."]
    return []


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

    image_path_errors = validate_image_paths(data_payload)
    errors.extend(image_path_errors)

    schedule_errors = validate_repeating_schedule_data(repeating_schedule_data)
    errors.extend(schedule_errors)

    # Return every logical input error to the caller in one result.
    return errors


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

    ai_input = {
        "module_count": module_count,
        "modules": data_payload["modules"],
        "repeating_schedule_data": repeating_schedule_data,
    }
    return ai_input, []
