"""Intake coordination; evidence lifetime belongs to the processing run."""

from .submission_validator import SubmissionValidator


class IOManager:
    def __init__(self, validator=None):
        self.validator = validator or SubmissionValidator()

    def accept(self, payload, evidence, base_directory=None):
        modules, errors = self.validator.validate(payload)
        if not modules:
            return None, errors
        accepted = []
        for module in modules:
            paths = module.get("file_paths")
            if not isinstance(paths, list) or not paths:
                paths = [module.get("file_path")]
            staged, issues = evidence.stage(paths, base_directory)
            errors.extend(issues)
            staged = [path for path in staged if path is not None]
            if staged:
                accepted.append(
                    {
                        "module_title": module["module_title"],
                        "credit": module["credit"],
                        "stored_file_path": staged[0],
                        "stored_file_paths": staged,
                    }
                )
        return (
            {"module_count": len(accepted), "modules": accepted} if accepted else None
        ), errors
