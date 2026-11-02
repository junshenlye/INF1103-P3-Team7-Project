"""The legacy JSONB payload is the wire format; no schema migration is needed."""

from copy import deepcopy
from hashlib import sha256
import json
from ..domain.module import Module
from .errors import DataManagerError


def calculate_module_snapshot_hash(modules):
    """Return a deterministic module snapshot hash for recommendation audits."""
    canonical = json.dumps(modules, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


class ResultSerializer:
    def encode(self, result):
        if result is None:
            return None
        return deepcopy(result.to_record() if hasattr(result, "to_record") else result)

    def decode(self, payload):
        # Keep optional/unknown legacy fields and the saved schedule unchanged.
        if payload is not None and not isinstance(payload, dict):
            raise DataManagerError("Saved result must be an object.")
        return deepcopy(payload)

    def modules(self, payload):
        try:
            return tuple(
                Module.from_record(record) for record in payload.get("modules", [])
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DataManagerError(f"Invalid saved module: {error}") from error
