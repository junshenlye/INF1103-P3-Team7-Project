"""One workflow for intake, extraction, domain planning and optional storage."""

from __future__ import annotations
import asyncio
import logging
import math
import os

from .pipeline_result import PipelineResult
from .processing_context import ProcessingContext
from ..io_manager import IOManager, EvidenceStore
from ..ai_manager import AIManager, RECOMMENDATION_PROMPT_VERSION, REASONING_MODEL
from ..logic_manager import (
    LogicManager,
    DEFAULT_RECOMMENDATION_TYPE,
    DEFAULT_STUDY_PREFERENCES,
)
from ..data_manager import (
    DataManager,
    PostgresRepository,
    DataManagerError,
    format_data_error,
)

LOGGER = logging.getLogger(__name__)


class PlanningService:
    def __init__(
        self, io=None, ai=None, logic=None, data=None, evidence_factory=EvidenceStore
    ):
        self.io = io or IOManager()
        self.ai = ai or AIManager()
        self.logic = logic or LogicManager()
        self.data = data
        self.evidence_factory = evidence_factory

    async def advice(self, project, kind, preferences, errors):
        preferences = self.logic.recommendations.normalize_study_preferences(
            preferences
        )
        raw, _ = await self.ai.process_recommendation(
            project, kind, preferences, errors
        )
        if raw is None:
            return None, preferences
        try:
            plan = self.logic.recommendations.validate(raw, kind, project, preferences)
            return plan, preferences
        except (KeyError, TypeError, ValueError) as error:
            errors.append(f"Logic Manager error: Invalid AI recommendation: {error}")
            return None, preferences

    async def run(
        self,
        submission,
        base_directory=None,
        project_id=None,
        project_name="Stackplan",
        timeout=1800,
    ):
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Pipeline timeout must be a positive finite number.")
        context = ProcessingContext(project_id=project_id)
        try:
            with self.evidence_factory() as evidence:
                try:
                    await asyncio.wait_for(
                        self._process(
                            submission, base_directory, project_name, evidence, context
                        ),
                        timeout,
                    )
                except asyncio.TimeoutError:
                    context.issues.append(
                        f"Pipeline timed out after {timeout:g} seconds during {context.stage}."
                    )
                except Exception as error:
                    # Outer boundary retains diagnostics and any factual schedule.
                    LOGGER.exception("Pipeline failed during %s", context.stage)
                    context.issues.append(
                        f"Pipeline error during {context.stage}: {error}"
                    )
        except OSError as error:
            context.issues.append(f"IO Manager error: {error}")
        if self.data is not None and context.run_id is not None:
            try:
                self.data.finish(context, context.payload, context.recommendation)
            except DataManagerError as error:
                context.issues.append(format_data_error(error))
        return PipelineResult(context.payload, tuple(context.issues))

    async def _process(
        self, submission, base_directory, project_name, evidence, context
    ):
        intake, errors = self.io.accept(submission, evidence, base_directory)
        context.issues.extend(errors)
        if self.data is not None:
            try:
                context.project_id, context.run_id = self.data.begin(
                    project_name,
                    intake["module_count"] if intake else 0,
                    context.project_id,
                )
            except DataManagerError as error:
                context.issues.append(format_data_error(error))
        if intake is None:
            return
        context.stage = "AI Manager"
        extracted, _ = await self.ai.process_payload(intake, context.issues)
        if extracted is None:
            return
        context.stage = "Logic Manager"
        context.modules, schedule = self.logic.build(
            extracted["modules"], context.issues
        )
        if not context.modules:
            return
        context.payload = {
            "module_count": len(context.modules),
            "modules": [module.to_record() for module in context.modules],
            "schedule": schedule.to_record(),
        }
        context.stage = "AI Study Plan"
        plan, preferences = await self.advice(
            context.payload,
            DEFAULT_RECOMMENDATION_TYPE,
            DEFAULT_STUDY_PREFERENCES,
            context.issues,
        )
        if plan is not None:
            advice = plan.to_record()
            context.payload.update(study_plan=advice, study_preferences=preferences)
            context.recommendation = {
                "recommendation_type": DEFAULT_RECOMMENDATION_TYPE,
                "modules": context.payload["modules"],
                "preferences": preferences,
                "recommendation": advice,
                "prompt_version": RECOMMENDATION_PROMPT_VERSION,
                "model_name": REASONING_MODEL,
            }


def create_service():
    """Resolve process configuration; managers hold no request state."""
    url = os.getenv("DATABASE_URL")
    return PlanningService(data=DataManager(PostgresRepository(url)) if url else None)
