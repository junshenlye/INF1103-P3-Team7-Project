"""Validated preparation advice, kept separate from confirmed deadlines."""

from __future__ import annotations
from dataclasses import dataclass, field
import math

from . import DomainError, freeze, thaw


@dataclass(frozen=True)
class StudyTask:
    title: str
    assessment_id: str | None
    week: int | None
    estimated_hours: float
    timing_status: str

    def __post_init__(self):
        if not isinstance(self.title, str) or not self.title.strip():
            raise DomainError("Preparation task title is required.")
        if self.assessment_id is not None and not isinstance(self.assessment_id, str):
            raise DomainError(
                "Preparation assessment identity must be text or unknown."
            )
        if (
            type(self.estimated_hours) not in (int, float)
            or not math.isfinite(self.estimated_hours)
            or self.estimated_hours <= 0
        ):
            raise DomainError("Preparation hours must be positive and finite.")
        if self.timing_status == "date_unknown":
            if self.week is not None:
                raise DomainError(
                    "Unknown assessment dates cannot have preparation weeks."
                )
        elif (
            self.timing_status != "recommended"
            or type(self.week) is not int
            or not 1 <= self.week <= 14
        ):
            raise DomainError(
                "Preparation needs a recommended week or explicit uncertainty."
            )


@dataclass(frozen=True)
class StudyPlan:
    recommendation_type: str
    summary: str
    _advice: object
    tasks: tuple[StudyTask, ...] = field(init=False)

    def __post_init__(self):
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise DomainError("Study advice requires a summary.")
        if self.recommendation_type not in {
            "work_checklist",
            "trimester_revision_plan",
        }:
            raise DomainError("Unsupported study plan type.")
        records = list(self._advice.get("items", []))
        records.extend(
            item for week in self._advice.get("weeks", []) for item in week["items"]
        )
        records.extend(self._advice.get("flexible_items", []))
        object.__setattr__(
            self,
            "tasks",
            tuple(
                StudyTask(
                    item["title"],
                    item["assessment_id"],
                    item["week"],
                    item["estimated_hours"],
                    item["timing_status"],
                )
                for item in records
            ),
        )
        object.__setattr__(self, "_advice", freeze(self._advice))

    @property
    def flexible_tasks(self):
        return tuple(task for task in self.tasks if task.week is None)

    def weekly_hours(self):
        totals = {}
        for task in self.tasks:
            if task.week is not None:
                totals[task.week] = round(
                    totals.get(task.week, 0) + task.estimated_hours, 2
                )
        return freeze(totals)

    @classmethod
    def from_validated(cls, record):
        return cls(record["recommendation_type"], record["summary"], record)

    def to_record(self):
        return thaw(self._advice)
