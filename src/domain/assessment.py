"""Stable assessment identity, occurrences, weights and timing."""

from __future__ import annotations
from dataclasses import dataclass
import math

from . import DomainError, thaw
from .assessment_timing import AssessmentTiming


@dataclass(frozen=True)
class Assessment:
    assessment_id: str
    name: str
    timing: AssessmentTiming
    record_role: str = "assessment"
    occurrence_number: int = 1
    occurrence_count: int = 1
    weight_percent: float | None = None
    weight_scope: str = "unknown"
    weight_scope_name: str | None = None
    parent_assessment_id: str | None = None
    details: str | None = None

    def __post_init__(self):
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.assessment_id, self.name)
        ):
            raise DomainError("Assessment identity and name are required.")
        if not isinstance(self.timing, AssessmentTiming):
            raise DomainError("Assessment timing is required.")
        if self.record_role not in {"assessment", "group"}:
            raise DomainError("Invalid assessment role.")
        if (
            type(self.occurrence_number) is not int
            or type(self.occurrence_count) is not int
            or not 1 <= self.occurrence_number <= self.occurrence_count
        ):
            raise DomainError("Invalid assessment occurrence.")
        if self.weight_scope not in {"module", "part", "group", "unknown"}:
            raise DomainError("Invalid weight scope.")
        if self.weight_percent is not None and (
            type(self.weight_percent) not in (int, float)
            or not math.isfinite(self.weight_percent)
        ):
            raise DomainError("Assessment weight must be finite or unknown.")
        if self.parent_assessment_id == self.assessment_id:
            raise DomainError("An assessment cannot be its own parent.")
        for field in ("details", "weight_scope_name", "parent_assessment_id"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, str):
                raise DomainError(f"Assessment {field} must be text or unknown.")

    @classmethod
    def from_record(cls, record):
        fields = {
            key: record[key]
            for key in cls.__dataclass_fields__
            if key != "timing" and key in record
        }
        return cls(
            **fields, timing=AssessmentTiming.from_record(record.get("schedule") or {})
        )

    def to_record(self):
        record = {
            key: thaw(getattr(self, key))
            for key in self.__dataclass_fields__
            if key != "timing"
        }
        record["schedule"] = self.timing.to_record()
        return record

    def placements(self):
        if self.record_role == "group":
            return [], None
        return self.timing.placements(self.occurrence_number, self.occurrence_count)

    def importance(self, credits, group_weight):
        if self.weight_percent is not None and self.weight_scope == "module":
            return round(credits * self.weight_percent / 100, 3), "calculated"
        if self.weight_percent is None and group_weight is not None:
            return None, "group_total_only"
        return (
            None,
            "non_module_weight"
            if self.weight_percent is not None
            else "weight_unknown",
        )
