"""Modules compose typed groups while preserving source notes and uncertainty."""

from __future__ import annotations
from dataclasses import dataclass, field
import math

from . import DomainError, freeze, thaw
from .assessment import Assessment


@dataclass(frozen=True)
class AssessmentGroup:
    type: str
    assessments: tuple[Assessment, ...] = ()
    group_weight_percent: float | None = None
    group_weight_scope: str = "unknown"
    group_weight_scope_name: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "assessments", tuple(self.assessments))
        if not isinstance(self.type, str) or not self.type.strip():
            raise DomainError("Assessment group type is required.")
        if any(not isinstance(item, Assessment) for item in self.assessments):
            raise DomainError("Group members must be assessments.")
        if self.group_weight_scope not in {"module", "part", "group", "unknown"}:
            raise DomainError("Invalid group weight scope.")
        if self.group_weight_scope_name is not None and not isinstance(
            self.group_weight_scope_name, str
        ):
            raise DomainError("Group weight scope name must be text or unknown.")
        if self.group_weight_percent is not None and (
            type(self.group_weight_percent) not in (int, float)
            or not math.isfinite(self.group_weight_percent)
        ):
            raise DomainError("Group weight must be finite or unknown.")

    @classmethod
    def from_record(cls, record):
        return cls(
            record["type"],
            tuple(
                Assessment.from_record(item) for item in record.get("assessments", [])
            ),
            record.get("group_weight_percent"),
            record.get("group_weight_scope", "unknown"),
            record.get("group_weight_scope_name"),
        )

    def to_record(self):
        return {
            "type": self.type,
            "declared_count": len(self.assessments),
            "group_weight_percent": self.group_weight_percent,
            "group_weight_scope": self.group_weight_scope,
            "group_weight_scope_name": self.group_weight_scope_name,
            "assessments": [item.to_record() for item in self.assessments],
        }


@dataclass(frozen=True)
class Module:
    module_title: str
    credit: float
    groups: tuple[AssessmentGroup, ...] = ()
    source_coverage: object = field(default_factory=dict)
    notes: tuple = ()
    follow_ups: tuple = ()

    def __post_init__(self):
        if not isinstance(self.module_title, str) or not self.module_title.strip():
            raise DomainError("Module title is missing.")
        if type(self.credit) not in (int, float) or not math.isfinite(self.credit):
            raise DomainError("Credit value is invalid.")
        object.__setattr__(self, "groups", tuple(self.groups))
        if any(not isinstance(group, AssessmentGroup) for group in self.groups):
            raise DomainError("Module groups must be assessment groups.")
        ids = [item.assessment_id for item in self.assessments]
        if len(ids) != len(set(ids)):
            raise DomainError("Module contains duplicate assessment IDs.")
        for name in ("source_coverage", "notes", "follow_ups"):
            object.__setattr__(self, name, freeze(getattr(self, name)))

    @property
    def assessments(self):
        return tuple(item for group in self.groups for item in group.assessments)

    @classmethod
    def from_record(cls, record):
        return cls(
            record["module_title"],
            record["credit"],
            tuple(
                AssessmentGroup.from_record(group)
                for group in record.get("assessment_types", [])
            ),
            record.get("source_coverage", {}),
            record.get("notes", []),
            record.get("follow_ups", []),
        )

    def to_record(self):
        return {
            "module_title": self.module_title,
            "credit": self.credit,
            "assessment_types": [group.to_record() for group in self.groups],
            "source_coverage": thaw(self.source_coverage),
            "notes": thaw(self.notes),
            "follow_ups": thaw(self.follow_ups),
        }

    def comments_for(self, assessment, assessment_type):
        targets = {assessment.name.casefold(), assessment_type.casefold()}
        comments = []
        for issue in self.follow_ups:
            target = issue.get("assessment")
            if issue.get("assessment_id") == assessment.assessment_id or (
                issue.get("assessment_id") is None
                and isinstance(target, str)
                and target.casefold() in targets
            ):
                if issue["message"] not in comments:
                    comments.append(issue["message"])
        return comments
