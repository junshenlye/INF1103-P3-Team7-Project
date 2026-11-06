"""Small HTTP adapter connecting a future frontend to Stackplan's core CLI."""

import asyncio
from datetime import date, datetime
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

from src import ai_manager, data_manager, logic_manager


LOGGER = logging.getLogger(__name__)
APP = Flask(__name__)
APP.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


def json_ready(value):
    """Convert database timestamps and nested values into JSON-safe data."""
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def error_response(message, status_code):
    """Return the API's consistent error document."""
    return jsonify({"payload": None, "errors": [message]}), status_code


@APP.after_request
def add_frontend_headers(response):
    """Allow the separately hosted development frontend to call this helper."""
    response.headers["Access-Control-Allow-Origin"] = os.getenv(
        "FRONTEND_ORIGIN",
        "http://localhost:5173",
    )
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@APP.get("/health")
def health():
    """Report whether the API adapter can reach PostgreSQL."""
    try:
        healthy = data_manager.check_connection()
    except data_manager.DataManagerError as error:
        return error_response(data_manager.format_data_error(error), 503)
    return jsonify({"status": "healthy" if healthy else "unhealthy"})


@APP.route("/api/projects", methods=["GET", "POST"])
def projects():
    """List projects or create a new trimester project."""
    try:
        if request.method == "GET":
            return jsonify({"payload": json_ready(data_manager.list_projects()), "errors": []})
        body = request.get_json(silent=True) or {}
        project = data_manager.create_project(
            body.get("name"),
            body.get("week_count", 14),
        )
        return jsonify({"payload": json_ready(project), "errors": []}), 201
    except data_manager.DataManagerError as error:
        return error_response(data_manager.format_data_error(error), 400)


@APP.get("/api/projects/<int:project_id>")
def project_detail(project_id):
    """Return stored modules and recommendations for one project."""
    try:
        project = data_manager.get_project_overview(project_id)
    except data_manager.DataManagerError as error:
        return error_response(data_manager.format_data_error(error), 500)
    if project is None:
        return error_response("Project not found.", 404)
    return jsonify({"payload": json_ready(project), "errors": []})


@APP.post("/api/projects/<int:project_id>/process")
def process_project(project_id):
    """Stage uploaded module images and invoke the core CLI unchanged."""
    try:
        if data_manager.get_project(project_id) is None:
            return error_response("Project not found.", 404)
    except data_manager.DataManagerError as error:
        return error_response(data_manager.format_data_error(error), 500)
    try:
        metadata = json.loads(request.form.get("modules", "[]"))
    except json.JSONDecodeError:
        return error_response("modules must be valid JSON.", 400)
    if not isinstance(metadata, list) or not metadata:
        return error_response("modules must be a non-empty array.", 400)

    with tempfile.TemporaryDirectory(prefix="stackplan-api-") as temporary_path:
        directory = Path(temporary_path)
        modules = []
        for position, module in enumerate(metadata):
            if not isinstance(module, dict):
                return error_response(f"Module {position} is invalid.", 400)
            file_fields = module.get("file_fields")
            if not isinstance(file_fields, list) or not file_fields:
                file_field = module.get("file_field")
                file_fields = [file_field] if isinstance(file_field, str) else []
            uploads = [request.files.get(field) for field in file_fields]
            if not uploads or any(
                upload is None or not upload.filename for upload in uploads
            ):
                return error_response(
                    f"Module {position} has missing uploaded evidence.",
                    400,
                )

            stored_names = []
            for upload in uploads:
                safe_name = secure_filename(upload.filename)
                suffix = Path(safe_name).suffix.lower()
                stored_name = f"{uuid.uuid4().hex}{suffix}"
                upload.save(directory / stored_name)
                stored_names.append(stored_name)
            modules.append(
                {
                    "module_title": module.get("module_title"),
                    "credit": module.get("credit"),
                    "file_paths": stored_names,
                }
            )

        manifest_path = directory / "payload.json"
        manifest_path.write_text(
            json.dumps({"module_count": len(modules), "modules": modules}),
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment["STACKPLAN_PROJECT_ID"] = str(project_id)
        completed = subprocess.run(
            [sys.executable, "-m", "src.main", str(manifest_path)],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=int(os.getenv("PIPELINE_TIMEOUT_SECONDS", "1800")),
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        LOGGER.error("Pipeline returned unreadable output: %s", completed.stderr)
        return error_response("Pipeline returned unreadable output.", 500)
    status_code = 200 if result.get("payload") is not None else 422
    return jsonify(result), status_code


@APP.route("/api/projects/<int:project_id>/recommendations", methods=["GET", "POST"])
def recommendations(project_id):
    """List stored recommendations or generate one validated candidate."""
    try:
        if request.method == "GET":
            stored = data_manager.list_recommendations(project_id)
            return jsonify({"payload": json_ready(stored), "errors": []})

        body = request.get_json(silent=True) or {}
        recommendation_type = body.get("recommendation_type")
        preferences = body.get("preferences", {})
        latest_result = data_manager.get_latest_pipeline_result(project_id)
        modules = (
            latest_result.get("modules", [])
            if isinstance(latest_result, dict)
            else []
        )
        schedule = (
            latest_result.get("schedule")
            if isinstance(latest_result, dict)
            else None
        )
        if not modules or not isinstance(schedule, dict):
            return error_response("Project has no saved pipeline result.", 404)
        project_payload = {
            "module_count": len(modules),
            "modules": modules,
            "schedule": schedule,
        }
        errors = []
        normalized_preferences = logic_manager.normalize_study_preferences(
            preferences
        )
        raw_recommendation, errors = asyncio.run(
            ai_manager.process_recommendation(
                project_payload,
                recommendation_type,
                normalized_preferences,
                errors,
            )
        )
        recommendation = None
        if raw_recommendation is not None:
            recommendation, errors = logic_manager.process_recommendation(
                raw_recommendation,
                recommendation_type,
                project_payload,
                normalized_preferences,
                errors,
            )
        if recommendation is None:
            return jsonify({"payload": None, "errors": errors}), 422
        stored = data_manager.save_recommendation(
            project_id,
            recommendation_type,
            modules,
            normalized_preferences,
            recommendation,
            ai_manager.RECOMMENDATION_PROMPT_VERSION,
            ai_manager.REASONING_MODEL,
        )
        return jsonify({"payload": json_ready(stored), "errors": errors}), 201
    except data_manager.DataManagerError as error:
        return error_response(data_manager.format_data_error(error), 500)
    except ValueError as error:
        return error_response(str(error), 400)


@APP.post(
    "/api/projects/<int:project_id>/recommendations/<int:recommendation_id>/status"
)
def recommendation_status(project_id, recommendation_id):
    """Accept or dismiss a generated recommendation."""
    body = request.get_json(silent=True) or {}
    try:
        stored = data_manager.set_recommendation_status(
            project_id,
            recommendation_id,
            body.get("status"),
        )
        return jsonify({"payload": json_ready(stored), "errors": []})
    except data_manager.DataManagerError as error:
        return error_response(data_manager.format_data_error(error), 400)


def main():
    """Run the HTTP adapter for local Compose development."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    APP.run(
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
