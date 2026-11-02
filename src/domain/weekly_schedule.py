"""A schedule owns generated appearances, independent of source assessments."""

from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Mapping

from . import DomainError, freeze, thaw


@dataclass(frozen=True)
class ScheduleEntry:
    assessment_id: str
    slot_role: str
    _details: object

    def __post_init__(self):
        if not isinstance(self.assessment_id, str) or not self.assessment_id.strip():
            raise DomainError("Schedule entries require an assessment identity.")
        if self.slot_role not in {"due", "active", "occurrence", "unscheduled"}:
            raise DomainError("Invalid schedule appearance role.")
        if (
            not isinstance(self._details, Mapping)
            or self._details.get("assessment_id") != self.assessment_id
            or self._details.get("slot_role") != self.slot_role
        ):
            raise DomainError(
                "Schedule entry details must match its identity and role."
            )
        object.__setattr__(self, "_details", freeze(self._details))

    @classmethod
    def from_record(cls, record):
        return cls(record["assessment_id"], record["slot_role"], record)

    def to_record(self):
        return thaw(self._details)


@dataclass(frozen=True)
class WeeklySchedule:
    weeks: tuple
    unscheduled: tuple[ScheduleEntry, ...]
    _metadata: object

    @classmethod
    def from_record(cls, record):
        weeks = tuple(
            (
                week["week"],
                week.get("is_recess", False),
                tuple(ScheduleEntry.from_record(item) for item in week["items"]),
            )
            for week in record["weeks"]
        )
        return cls(
            weeks,
            tuple(ScheduleEntry.from_record(item) for item in record["unscheduled"]),
            {
                key: value
                for key, value in record.items()
                if key not in {"weeks", "unscheduled"}
            },
        )

    def __post_init__(self):
        object.__setattr__(
            self,
            "weeks",
            tuple(
                (number, recess, tuple(items)) for number, recess, items in self.weeks
            ),
        )
        object.__setattr__(self, "unscheduled", tuple(self.unscheduled))
        object.__setattr__(self, "_metadata", freeze(self._metadata))
        numbers = [number for number, _, _ in self.weeks]
        if len(numbers) != len(set(numbers)):
            raise DomainError("Schedule has duplicate week buckets.")

    def to_record(self):
        return {
            **thaw(self._metadata),
            "weeks": [
                {
                    "week": number,
                    "is_recess": recess,
                    "items": [item.to_record() for item in items],
                }
                for number, recess, items in self.weeks
            ],
            "unscheduled": [item.to_record() for item in self.unscheduled],
        }
