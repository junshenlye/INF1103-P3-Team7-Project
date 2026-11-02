"""Immutable outcome with the existing payload/errors response contract."""

from __future__ import annotations
from dataclasses import dataclass
from ..domain import freeze, thaw


@dataclass(frozen=True)
class PipelineResult:
    _payload: object
    errors: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "_payload", freeze(self._payload))
        object.__setattr__(self, "errors", tuple(self.errors))

    @property
    def payload(self):
        return thaw(self._payload)

    @property
    def status(self):
        return (
            "failed"
            if self._payload is None
            else "partial"
            if self.errors
            else "completed"
        )

    def to_record(self):
        return {"payload": self.payload, "errors": list(self.errors)}
