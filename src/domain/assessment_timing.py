"""Confirmed timing and uncertainty; source words never imply invented dates."""

from __future__ import annotations
from dataclasses import dataclass

from . import DomainError

WEEK_COUNT = 14
RECESS_WEEKS = (7,)


@dataclass(frozen=True)
class AssessmentTiming:
    kind: str = "unknown"
    week: int | None = None
    start_week: int | None = None
    end_week: int | None = None
    raw: str | None = None

    def __post_init__(self):
        if any(
            value is not None and type(value) is not int
            for value in (self.week, self.start_week, self.end_week)
        ):
            raise DomainError("Timing weeks must be integers or unknown.")
        if self.raw is not None and not isinstance(self.raw, str):
            raise DomainError("Timing source wording must be text or unknown.")
        if self.kind not in {"week", "week_range", "recurring", "unknown"}:
            raise DomainError("Unsupported assessment timing kind.")
        if self.kind == "week" and type(self.week) is not int:
            raise DomainError("An explicit week requires an integer.")
        if self.kind == "week_range" and (
            type(self.start_week) is not int or type(self.end_week) is not int
        ):
            raise DomainError("A week range requires both integer bounds.")
        if self.kind == "recurring" and not isinstance(self.raw, str):
            raise DomainError("A recurrence requires source wording.")

    @classmethod
    def from_record(cls, record):
        return cls(
            **{
                key: record.get(key)
                for key in ("week", "start_week", "end_week", "raw")
            },
            kind=record.get("kind", "unknown"),
        )

    def to_record(self):
        return {
            "kind": self.kind,
            "week": self.week,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "raw": self.raw,
        }

    def placements(self, occurrence=1, count=1):
        if (
            type(occurrence) is not int
            or type(count) is not int
            or not 1 <= occurrence <= count
        ):
            raise DomainError("Invalid assessment occurrence.")
        if self.kind == "week":
            if 1 <= self.week <= WEEK_COUNT:
                return [(self.week, "due")], None
            return [], "week_out_of_range"
        complete_range = (
            type(self.start_week) is int
            and type(self.end_week) is int
            and 1 <= self.start_week <= self.end_week <= WEEK_COUNT
        )
        if self.kind == "week_range":
            if complete_range:
                placements = [
                    (week, "active")
                    for week in range(self.start_week, self.end_week + 1)
                    if week not in RECESS_WEEKS
                ]
                return (placements, None) if placements else ([], "week_range_invalid")
            return [], "week_range_invalid"
        if self.kind == "recurring":
            if complete_range:
                teaching = [
                    week
                    for week in range(self.start_week, self.end_week + 1)
                    if week not in RECESS_WEEKS
                ]
                if len(teaching) == count:
                    return [(teaching[occurrence - 1], "occurrence")], None
            return [], "recurrence_unresolved"
        return [], "week_not_stated"
