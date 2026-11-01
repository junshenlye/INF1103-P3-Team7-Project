"""Deterministic test doubles only at the provider and repository boundaries."""

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

from src.ai_manager import RELEVANCE_MODEL
from src.data_manager import DataManagerError


def extraction(week=3):
    return {
        "source_coverage": {"status": "appears_complete", "comment": None},
        "assessment_types": [
            {
                "type": "quiz",
                "group_weight_percent": None,
                "assessments": [
                    {
                        "name": "Quiz",
                        "weight_percent": 20,
                        "weight_scope": "module",
                        "schedule": {
                            "kind": "week",
                            "week": week,
                            "start_week": None,
                            "end_week": None,
                            "raw": f"Week {week}",
                        },
                    }
                ],
            }
        ],
        "notes": [],
        "follow_ups": [],
    }


class FakeProvider:
    def __init__(
        self,
        fail_modules=(),
        malformed_modules=(),
        invalid_plan=False,
        delay=0,
        advice_delay=0,
        invalid_structure=False,
    ):
        self.fail_modules = set(fail_modules)
        self.malformed_modules = set(malformed_modules)
        self.invalid_plan = invalid_plan
        self.invalid_structure = invalid_structure
        self.delay = delay
        self.advice_delay = advice_delay
        self.closed = False
        self.requests = []
        self.active = 0
        self.maximum = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.complete))

    async def close(self):
        self.closed = True

    async def complete(self, **request):
        self.requests.append(request)
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(self.delay)
            content = request["messages"][0]["content"]
            if isinstance(content, list):
                text = content[0]["text"]
                title = text.split("MODULE: ")[-1].split("\n")[0]
                if title in self.fail_modules:
                    raise ConnectionError("provider unavailable")
                if title in self.malformed_modules:
                    output = "invalid JSON"
                elif request["model"] == RELEVANCE_MODEL:
                    output = json.dumps(
                        {"relevant": True, "detected_module_title": title}
                    )
                elif "INTERPRETATION MEMO:" in text:
                    output = json.dumps(
                        {"assessment_types": "invalid"}
                        if self.invalid_structure
                        else extraction()
                    )
                else:
                    output = "Source-faithful interpretation memo"
            else:
                await asyncio.sleep(self.advice_delay)
                context = json.loads(content.split("INPUT DATA:\n")[-1])
                project = context["confirmed_project"]
                first = project["modules"][0]
                item = {
                    "title": "Prepare quiz",
                    "assessment_id": "invented"
                    if self.invalid_plan
                    else first["assessment_types"][0]["assessments"][0][
                        "assessment_id"
                    ],
                    "module_title": first["module_title"],
                    "week": 2,
                    "estimated_hours": 2,
                    "priority": "medium",
                    "reason": "Review before the confirmed quiz",
                }
                # Prompts are the existing concrete behaviours, not an application branch.
                if '"work_checklist"' in content.split("INPUT DATA:")[0]:
                    output = json.dumps(
                        {
                            "recommendation_type": "work_checklist",
                            "summary": "Prepare steadily",
                            "items": [item],
                        }
                    )
                else:
                    output = json.dumps(
                        {
                            "recommendation_type": "trimester_revision_plan",
                            "summary": "Prepare steadily",
                            "weeks": [{"week": 2, "focus": "Quiz", "items": [item]}],
                        }
                    )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=output))]
            )
        finally:
            self.active -= 1


class MemoryRepository:
    """Contract double with copy isolation, rollback and legacy payload preservation."""

    def __init__(self):
        self.projects = {}
        self.runs = {}
        self.recommendations = {}

    def check_connection(self):
        return True

    def list_projects(self):
        return deepcopy(list(reversed(self.projects.values())))

    def get_or_create_project(self, name, week_count=14, project_id=None):
        if project_id is not None:
            if project_id not in self.projects:
                raise DataManagerError("Project does not exist.")
            return deepcopy(self.projects[project_id])
        for project in self.projects.values():
            if project["name"] == name:
                return deepcopy(project)
        return self.create_project(name, week_count)

    def create_project(self, name, week_count=14):
        project = {"id": len(self.projects) + 1, "name": name, "week_count": week_count}
        self.projects[project["id"]] = project
        return deepcopy(project)

    def get_project(self, project_id):
        return deepcopy(self.projects.get(project_id))

    def start_pipeline_run(self, project_id, requested_module_count):
        run_id = len(self.runs) + 1
        self.runs[run_id] = {
            "id": run_id,
            "project_id": project_id,
            "status": "running",
        }
        return run_id

    def save_pipeline_result(self, project_id, run_id, payload, errors):
        if run_id not in self.runs or self.runs[run_id]["project_id"] != project_id:
            raise DataManagerError("Pipeline run does not exist.")
        self.runs[run_id].update(
            result_payload=deepcopy(payload),
            errors=list(errors),
            status="failed"
            if payload is None
            else "partial"
            if errors
            else "completed",
        )

    def get_latest_pipeline_result(self, project_id):
        rows = [
            run
            for run in self.runs.values()
            if run["project_id"] == project_id and run.get("result_payload") is not None
        ]
        return deepcopy(rows[-1]["result_payload"]) if rows else None

    def list_pipeline_runs(self, project_id):
        return deepcopy(
            [
                row
                for row in reversed(list(self.runs.values()))
                if row["project_id"] == project_id
            ]
        )

    def save_recommendation(
        self,
        project_id,
        recommendation_type,
        modules,
        preferences,
        recommendation,
        prompt_version,
        model_name,
    ):
        if recommendation_type not in {"work_checklist", "trimester_revision_plan"}:
            raise DataManagerError("Invalid recommendation type.")
        row = {
            "id": len(self.recommendations) + 1,
            "project_id": project_id,
            "recommendation_type": recommendation_type,
            "status": "candidate",
            "recommendation_payload": deepcopy(recommendation),
        }
        self.recommendations[row["id"]] = row
        return deepcopy(row)

    def list_recommendations(self, project_id):
        return deepcopy(
            [
                row
                for row in reversed(list(self.recommendations.values()))
                if row["project_id"] == project_id
            ]
        )

    def set_recommendation_status(self, project_id, recommendation_id, status):
        row = self.recommendations.get(recommendation_id)
        if row is None or row["project_id"] != project_id:
            raise DataManagerError("Recommendation does not exist.")
        if status not in {"candidate", "accepted", "dismissed"}:
            raise DataManagerError("Recommendation status is invalid.")
        if status == "accepted":
            for candidate in self.recommendations.values():
                if (
                    candidate["project_id"] == project_id
                    and candidate["recommendation_type"] == row["recommendation_type"]
                    and candidate["status"] == "accepted"
                ):
                    candidate["status"] = "dismissed"
        row["status"] = status
        return deepcopy(row)

    def complete_run(self, project_id, run_id, payload, errors, recommendation=None):
        before = deepcopy((self.runs, self.recommendations))
        try:
            self.save_pipeline_result(project_id, run_id, payload, errors)
            if recommendation is not None:
                self.save_recommendation(project_id=project_id, **recommendation)
        except Exception:
            self.runs, self.recommendations = before
            raise
