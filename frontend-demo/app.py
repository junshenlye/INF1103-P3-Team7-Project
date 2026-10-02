"""Standalone Flask frontend for the trimester pacing pipeline."""

import json
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from urllib import error as url_error
from urllib import request as url_request

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


FRONTEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FRONTEND_ROOT.parent
UPLOAD_ROOT = PROJECT_ROOT / ".runtime-uploads"
BACKEND_UPLOAD_ROOT = Path("/app/uploads")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import data_manager  # noqa: E402


LOGGER = logging.getLogger(__name__)


def load_dashboard(api_url=None):
    """Read locally by default, retaining an explicit remote-API option."""
    if not api_url:
        dashboard = data_manager.load_plan()
        return dashboard, None
    try:
        with url_request.urlopen(f"{api_url}/api/dashboard", timeout=8) as response:
            return json.loads(response.read().decode("utf-8")), None
    except (OSError, ValueError, json.JSONDecodeError, url_error.HTTPError):
        return {
            "modules": [],
        }, f"The configured API is unavailable at {api_url}."


def save_uploaded_files(uploaded_files, target_directory, name_prefix=""):
    """Save uploads for the lifetime of one local extraction request."""
    paths = []
    for index, uploaded_file in enumerate(uploaded_files):
        if not uploaded_file or not uploaded_file.filename:
            continue
        safe_name = secure_filename(uploaded_file.filename) or f"upload-{index}"
        path = Path(target_directory) / f"{name_prefix}{index}-{safe_name}"
        uploaded_file.save(path)
        path.chmod(0o644)

        relative_path = path.relative_to(UPLOAD_ROOT)
        backend_path = BACKEND_UPLOAD_ROOT / relative_path
        paths.append(str(backend_path))
    return paths


def send_backend_request(data_payload):
    """Send one JSON request to the persistent backend container."""
    request_text = json.dumps(data_payload)
    request_line = request_text + "\n"
    request_bytes = request_line.encode("utf-8")

    backend_host = os.getenv("BACKEND_HOST", "127.0.0.1")
    backend_port = int(os.getenv("BACKEND_PORT", "8000"))

    backend_socket = socket.create_connection(
        (backend_host, backend_port),
        timeout=10,
    )
    backend_socket.settimeout(300)
    with backend_socket:
        backend_file = backend_socket.makefile("rwb")
        backend_file.write(request_bytes)
        backend_file.flush()
        response_bytes = backend_file.readline()

    if not response_bytes:
        raise RuntimeError("The backend container returned no response.")

    response_text = response_bytes.decode("utf-8")
    return json.loads(response_text)


def frontend_modules(form, files, target_directory):
    """Build the module payload expected by the IO manager."""
    raw_module_count = form.get("module_count", "1")
    try:
        module_count = int(raw_module_count)
    except ValueError:
        module_count = 0

    limited_module_count = min(module_count, 21)
    safe_module_count = max(0, limited_module_count)
    modules = []
    for index in range(safe_module_count):
        raw_credit_units = form.get(f"credit_units_{index}", "")
        credit_units = None
        if raw_credit_units:
            try:
                credit_units = float(raw_credit_units)
            except ValueError:
                credit_units = raw_credit_units

        module_name = form.get(f"module_name_{index}", "")
        additional_context = form.get(f"additional_context_{index}", "")
        uploaded_files = files.getlist(f"source_files_{index}")
        image_paths = save_uploaded_files(
            uploaded_files,
            target_directory,
            name_prefix=f"module-{index}-",
        )

        module = {
            "module_name": module_name,
            "credit_units": credit_units,
            "additional_context": additional_context,
            "files": image_paths,
        }
        modules.append(module)

    actual_module_count = len(modules)
    raw_recess_weeks = form.get("recess_weeks", "")
    recess_weeks = []
    for raw_week in raw_recess_weeks.split(","):
        week_text = raw_week.strip()
        if not week_text:
            continue
        try:
            recess_week = int(week_text)
        except ValueError:
            recess_week = week_text
        recess_weeks.append(recess_week)

    return {
        "calendar": {"recess_weeks": recess_weeks},
        "module_count": actual_module_count,
        "modules": modules,
    }


def create_app(configured_api_url=None):
    """Create one standalone frontend and pipeline HTTP process."""
    load_dotenv(FRONTEND_ROOT.parent / ".env", override=False)
    api_url = configured_api_url.rstrip("/") if configured_api_url else None
    app = Flask(
        __name__,
        template_folder=str(FRONTEND_ROOT / "templates"),
        static_folder=str(FRONTEND_ROOT / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
    data_manager.initialize_storage()
    UPLOAD_ROOT.mkdir(exist_ok=True)

    @app.get("/")
    def index():
        dashboard, connection_error = load_dashboard(api_url)
        return render_template(
            "index.html",
            **dashboard,
            api_base_url=api_url or "",
            connection_error=connection_error,
        )

    @app.post("/api/extractions")
    def extraction_api():
        frontend_started_at = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(
                prefix="assessment-upload-",
                dir=UPLOAD_ROOT,
            ) as directory:
                directory_path = Path(directory)
                directory_path.chmod(0o755)
                data_payload = frontend_modules(
                    request.form,
                    request.files,
                    directory,
                )
                result = send_backend_request(data_payload)
        except Exception:
            LOGGER.exception("Assessment extraction stopped unexpectedly")
            frontend_finished_at = time.perf_counter()
            frontend_total_ms = round(
                (frontend_finished_at - frontend_started_at) * 1000,
                2,
            )
            error_result = {
                "errors": ["The assessment data could not be created."],
                "runtime": {"frontend_total_ms": frontend_total_ms},
            }
            return jsonify(error_result), 500

        frontend_finished_at = time.perf_counter()
        frontend_total_ms = round(
            (frontend_finished_at - frontend_started_at) * 1000,
            2,
        )
        runtime = result.get("runtime")
        if not isinstance(runtime, dict):
            runtime = {}
        runtime["frontend_total_ms"] = frontend_total_ms
        result["runtime"] = runtime
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.get("/api/data")
    def data_api():
        dashboard, connection_error = load_dashboard(api_url)
        if connection_error:
            return jsonify({"errors": [connection_error]}), 503
        return jsonify(dashboard)

    @app.get("/health")
    def health():
        if api_url:
            _dashboard, connection_error = load_dashboard(api_url)
            ready = connection_error is None
        else:
            ready = data_manager.storage_is_ready()
        return jsonify({"ok": ready}), (200 if ready else 503)

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return jsonify(
            {"errors": ["Combined upload size must not exceed 100 MB."]}
        ), 413

    return app


if __name__ == "__main__":
    create_app().run(
        host="127.0.0.1",
        port=int(os.getenv("FRONTEND_PORT", "5050")),
        debug=False,
    )
