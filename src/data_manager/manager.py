"""Application persistence coordination; consumers depend on repository behaviour."""

from .repository import PlanningRepository
from .serializers import ResultSerializer


class DataManager:
    def __init__(self, repository: PlanningRepository, serializer=None):
        self.repository = repository
        self.serializer = serializer or ResultSerializer()

    def begin(self, name, module_count, project_id=None):
        project = self.repository.get_or_create_project(name, project_id=project_id)
        return project["id"], self.repository.start_pipeline_run(
            project["id"], module_count
        )

    def finish(self, context, payload, recommendation=None):
        self.repository.complete_run(
            context.project_id,
            context.run_id,
            self.serializer.encode(payload),
            list(context.issues),
            recommendation,
        )

    def get_latest_pipeline_result(self, project_id):
        return self.serializer.decode(
            self.repository.get_latest_pipeline_result(project_id)
        )

    def get_project_overview(self, project_id):
        project = self.repository.get_project(project_id)
        if project is None:
            return None
        result = self.get_latest_pipeline_result(project_id) or {}
        return {
            **project,
            "modules": result.get("modules", []),
            "schedule": result.get("schedule"),
            "pipeline_runs": self.repository.list_pipeline_runs(project_id),
            "recommendations": self.repository.list_recommendations(project_id),
        }
