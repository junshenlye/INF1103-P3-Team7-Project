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


@APP.get("/api/projects/<int:project_id>/schedule")
def project_schedule(project_id):
    """Build the deterministic schedule from confirmed stored modules."""
    try:
        modules = data_manager.get_confirmed_modules(project_id)
        if not modules:
            return error_response("Project has no confirmed modules.", 404)
        errors = []
        schedule = logic_manager.build_weekly_schedule(modules, errors)
        return jsonify({"payload": schedule, "errors": errors})
    except data_manager.DataManagerError as error:
        return error_response(data_manager.format_data_error(error), 500)


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
            file_field = module.get("file_field")
            upload = request.files.get(file_field) if isinstance(file_field, str) else None
            if upload is None or not upload.filename:
                return error_response(f"Module {position} has no uploaded image.", 400)
            safe_name = secure_filename(upload.filename)
            suffix = Path(safe_name).suffix.lower()
            stored_name = f"{uuid.uuid4().hex}{suffix}"
            upload.save(directory / stored_name)
            modules.append(
                {
                    "module_title": module.get("module_title"),
                    "credit": module.get("credit"),
                    "file_path": stored_name,
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


@APP.post(
    "/api/projects/<int:project_id>/modules/<path:module_title>/confirm"
)
def confirm_module(project_id, module_title):
    """Activate one stored AI revision selected by the student."""
    body = request.get_json(silent=True) or {}
    revision = body.get("revision")
    if type(revision) is not int:
        return error_response("revision must be an integer.", 400)
    try:
        data_manager.confirm_module_revision(project_id, module_title, revision)
        return jsonify({"payload": {"confirmed": True}, "errors": []})
    except data_manager.DataManagerError as error:
        return error_response(data_manager.format_data_error(error), 400)


@APP.put("/api/projects/<int:project_id>/modules/<path:module_title>")
def edit_module(project_id, module_title):
    """Validate and save a confirmed student-edited module revision."""
    module = request.get_json(silent=True)
    if not isinstance(module, dict) or module.get("module_title") != module_title:
        return error_response("Edited module title does not match the URL.", 400)
    validation_errors = []
    try:
        logic_manager.build_weekly_schedule([module], validation_errors)
        if validation_errors:
            return jsonify({"payload": None, "errors": validation_errors}), 400
        saved = data_manager.save_confirmed_module_edit(project_id, module)
        return jsonify({"payload": json_ready(saved), "errors": []})
    except (KeyError, TypeError, ValueError) as error:
        return error_response(f"Edited module is invalid: {error}", 400)
    except data_manager.DataManagerError as error:
        return error_response(data_manager.format_data_error(error), 400)


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
        modules = data_manager.get_confirmed_modules(project_id)
        if not modules:
            return error_response("Project has no confirmed modules.", 404)
        schedule_errors = []
        project_payload = {
            "module_count": len(modules),
            "modules": modules,
            "schedule": logic_manager.build_weekly_schedule(
                modules,
                schedule_errors,
            ),
        }
        errors = list(schedule_errors)
        recommendation, errors = asyncio.run(
            ai_manager.process_recommendation(
                project_payload,
                recommendation_type,
                preferences,
                errors,
            )
        )
        if recommendation is None:
            return jsonify({"payload": None, "errors": errors}), 422
        stored = data_manager.save_recommendation(
            project_id,
            recommendation_type,
            modules,
            ai_manager.normalize_study_preferences(preferences),
            recommendation,
            ai_manager.PROMPT_VERSION,
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
