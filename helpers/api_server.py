"""Thin local HTTP adapter for the procedural core."""

import json
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile

from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_ROOT = PROJECT_ROOT / ".runtime-uploads"
BACKEND_UPLOAD_ROOT = Path("/app/uploads")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import data_manager  # noqa: E402


LOGGER = logging.getLogger(__name__)


def save_uploaded_files(uploaded_files, target_directory, name_prefix=""):
    """Save uploads only for the lifetime of one extraction."""
    file_paths = []
    for index, uploaded_file in enumerate(uploaded_files):
        if not uploaded_file or not uploaded_file.filename:
            continue
        safe_name = secure_filename(uploaded_file.filename) or f"upload-{index}"
        target_path = Path(target_directory) / f"{name_prefix}{index}-{safe_name}"
        uploaded_file.save(target_path)
        target_path.chmod(0o644)

        relative_path = target_path.relative_to(UPLOAD_ROOT)
        backend_path = BACKEND_UPLOAD_ROOT / relative_path
        file_paths.append(str(backend_path))
    return file_paths


def save_uploaded_images(uploaded_files, target_directory):
    """Backward-compatible alias for the former image-only endpoint."""
    return save_uploaded_files(uploaded_files, target_directory)


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


def _frontend_modules(form, files, target_directory):
    """Turn compact indexed multipart fields into the core request shape."""
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
    return {
        "module_count": actual_module_count,
        "modules": modules,
    }


def create_app():
    """Create the thin API without module-level application state."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 35 * 1024 * 1024

    @app.after_request
    def add_local_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.get("/")
    def api_index():
        return jsonify(
            {
                "name": "Stackplan development API",
                "health": "/health",
                "dashboard": "/api/dashboard",
                "frontend": "Run python frontend-demo/app.py on the host.",
            }
        )

    @app.get("/health")
    def health():
        database_ready = data_manager.storage_is_ready()
        return jsonify({"ok": database_ready, "database": database_ready}), (
            200 if database_ready else 503
        )

    @app.get("/api/dashboard")
    def dashboard_api():
        dashboard = data_manager.load_plan()
        return jsonify(dashboard)

    @app.post("/api/extractions")
    def extraction_api():
        try:
            UPLOAD_ROOT.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="assessment-upload-",
                dir=UPLOAD_ROOT,
            ) as directory:
                directory_path = Path(directory)
                directory_path.chmod(0o755)
                if "module_count" in request.form:
                    input_data = _frontend_modules(
                        request.form, request.files, directory
                    )
                else:
                    input_data = {
                        "module": request.form.get("module", ""),
                        "prompt": request.form.get("prompt", ""),
                        "image_paths": save_uploaded_images(
                            request.files.getlist("source_files"), directory
                        ),
                    }
                result = send_backend_request(input_data)
        except Exception:
            LOGGER.exception("Assessment extraction stopped unexpectedly")
            return jsonify({"errors": ["The schedule could not be created."]}), 500
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return jsonify({"errors": ["Combined upload size must not exceed 35 MB."]}), 413

    return app


def run_api():
    """Initialize storage, then expose the local API."""
    logging.basicConfig(level=logging.INFO)
    if not data_manager.initialize_storage():
        raise RuntimeError("PostgreSQL storage could not be initialized.")
    create_app().run(
        host="0.0.0.0",
        port=int(os.getenv("API_PORT", "8000")),
        debug=False,
        threaded=True,
    )


if __name__ == "__main__":
    run_api()
