"""Mutable state belongs to exactly one processing run."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ProcessingContext:
    stage: str = "IO Manager"
    issues: list[str] = field(default_factory=list)
    modules: tuple = ()
    project_id: int | None = None
    run_id: int | None = None
    payload: dict | None = None
    recommendation: dict | None = None
