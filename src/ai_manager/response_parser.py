"""Provider response syntax and structural contracts, before domain interpretation."""

import json


class ResponseValidationError(ValueError):
    pass


class ResponseParser:
    def parse(self, content):
        """Decode model text as JSON and return the resulting Python value.

        A single surrounding Markdown fence is accepted because models sometimes
        add it despite the prompt. Any other malformed output is a hard failure.
        """
        if not isinstance(content, str):
            raise ResponseValidationError("Model returned invalid JSON.")
        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1]).strip()
        try:
            return json.loads(stripped)
        except (TypeError, json.JSONDecodeError) as error:
            raise ResponseValidationError("Model returned invalid JSON.") from error


class ResponseValidator:
    def object(self, value, response_name):
        """Return a parsed model response only when its root is a JSON object.

        AI Manager validates the transport-level response contract. Logic Manager
        remains responsible for domain fields, business rules and scheduling.
        """
        if not isinstance(value, dict):
            raise ResponseValidationError(
                f"{response_name} response must be a JSON object."
            )
        return value

    def relevance(self, value):
        self.object(value, "Relevance")
        if type(value.get("relevant")) is not bool:
            raise ResponseValidationError("AI relevance response is invalid.")
        return value

    def normalization(self, value):
        self.object(value, "Normalization")
        groups = value.get("assessment_types")
        if not isinstance(groups, list):
            raise ResponseValidationError(
                "Normalization response has no assessment type list."
            )
        for group in groups:
            if (
                not isinstance(group, dict)
                or not isinstance(group.get("type"), str)
                or not isinstance(group.get("assessments"), list)
            ):
                raise ResponseValidationError(
                    "Normalization response contains an invalid group."
                )
            if any(
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not item["name"].strip()
                for item in group["assessments"]
            ):
                raise ResponseValidationError(
                    "Normalization response contains an invalid item."
                )
        return value
