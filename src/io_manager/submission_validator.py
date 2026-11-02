"""Submission metadata validation, independent of files and presentation."""

import logging

LOGGER = logging.getLogger(__name__)


def format_io_error(error):
    return f"IO Manager error: {error}"


class SubmissionValidator:
    def validate(self, payload):
        """Return valid module dictionaries and hard metadata errors.

        Invalid top-level fields stop the payload. Invalid module entries are
        removed individually so the remaining modules can continue.
        """
        if not isinstance(payload, dict):
            error = format_io_error("Payload must be a dictionary.")
            return (None, [error])
        module_count = payload.get("module_count")
        modules = payload.get("modules")
        errors = []
        if type(module_count) is not int:
            errors.append(format_io_error("module_count must be an integer."))
        if not isinstance(modules, list) or not modules:
            errors.append(format_io_error("modules must be a non-empty array."))
            return (None, errors)
        if type(module_count) is int and module_count != len(modules):
            errors.append(
                format_io_error("module_count must match the number of modules.")
            )
        if errors:
            return (None, errors)
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
        return (valid_modules, errors)
