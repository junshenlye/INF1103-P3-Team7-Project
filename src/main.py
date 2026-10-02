"""Coordinate the IO, AI, logic, and data managers."""

import json
import logging
import os
from pathlib import Path
import socket
import time

from dotenv import load_dotenv

from . import ai_manager, data_manager, io_manager, logic_manager


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def process_request(
    input_data,
    api_caller=None,
    repeating_schedule_data=None,
):
    """Coordinate the request from frontend input to the saved response.

    Flow: Frontend -> IO Manager -> AI Manager -> Logic Manager
          -> Data Manager -> Frontend response
    """
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    request_started_at = time.perf_counter()

    # IO Manager: validate the frontend payload and prepare the AI input.
    io_started_at = time.perf_counter()
    module_count = None
    if isinstance(input_data, dict):
        module_count = input_data.get("module_count")

    ai_input, errors = io_manager.prepare_ai_input(
        module_count,
        input_data,
        repeating_schedule_data,
    )
    io_finished_at = time.perf_counter()
    io_manager_ms = round((io_finished_at - io_started_at) * 1000, 2)
    if errors:
        request_finished_at = time.perf_counter()
        backend_total_ms = round((request_finished_at - request_started_at) * 1000, 2)
        runtime = {
            "io_manager_ms": io_manager_ms,
            "ai_manager_ms": None,
            "logic_manager_ms": None,
            "data_manager_ms": None,
            "backend_total_ms": backend_total_ms,
        }
        return {"ok": False, "errors": errors, "runtime": runtime}

    # AI Manager: interpret images, user context, and retry schedule context.
    ai_started_at = time.perf_counter()
    ai_result = ai_manager.process(
        ai_input,
        api_caller=api_caller,
    )
    ai_finished_at = time.perf_counter()
    ai_manager_ms = round((ai_finished_at - ai_started_at) * 1000, 2)

    # Logic Manager: preserve extracted facts and calculate schedule weights.
    logic_started_at = time.perf_counter()
    try:
        calendar = ai_input.get("calendar")
        logic_result = logic_manager.build_module_data(ai_result, calendar)
    except ValueError as error:
        logic_finished_at = time.perf_counter()
        request_finished_at = time.perf_counter()
        logic_manager_ms = round((logic_finished_at - logic_started_at) * 1000, 2)
        backend_total_ms = round((request_finished_at - request_started_at) * 1000, 2)
        runtime = {
            "io_manager_ms": io_manager_ms,
            "ai_manager_ms": ai_manager_ms,
            "logic_manager_ms": logic_manager_ms,
            "data_manager_ms": None,
            "backend_total_ms": backend_total_ms,
        }
        return {
            "ok": False,
            "status": "system_failure",
            "errors": [str(error)],
            "runtime": runtime,
        }

    # Logic Manager: report module failures without changing accepted data.
    result_status, result_errors = logic_manager.review_result(ai_result)
    logic_finished_at = time.perf_counter()
    logic_manager_ms = round((logic_finished_at - logic_started_at) * 1000, 2)

    # Data Manager: store the input, extraction, and weighted module data.
    data_started_at = time.perf_counter()
    saved = data_manager.save(
        input_data=ai_input,
        ai_result=ai_result,
        logic_result=logic_result,
    )
    data_finished_at = time.perf_counter()
    request_finished_at = time.perf_counter()
    data_manager_ms = round((data_finished_at - data_started_at) * 1000, 2)
    backend_total_ms = round((request_finished_at - request_started_at) * 1000, 2)
    runtime = {
        "io_manager_ms": io_manager_ms,
        "ai_manager_ms": ai_manager_ms,
        "logic_manager_ms": logic_manager_ms,
        "data_manager_ms": data_manager_ms,
        "backend_total_ms": backend_total_ms,
    }
    if not saved:
        return {
            "ok": False,
            "errors": ["The assessment data could not be saved."],
            "runtime": runtime,
        }

    extracted_count = 0
    for module in ai_result["modules"]:
        module_assessments = module["assessments"]
        assessment_count = len(module_assessments)
        extracted_count += assessment_count

    successful_modules = logic_result["modules"]
    if result_errors and not successful_modules:
        return {
            "ok": False,
            "status": result_status,
            "errors": result_errors,
            "failures": ai_result.get("failures", []),
            "models_used": ai_result.get("models_used", []),
            "model_runs": ai_result.get("model_runs", []),
            "runtime": runtime,
            **logic_result,
        }

    response = {
        "ok": True,
        "status": result_status,
        "extracted_count": extracted_count,
        "failures": ai_result.get("failures", []),
        "models_used": ai_result.get("models_used", []),
        "model_runs": ai_result.get("model_runs", []),
        "runtime": runtime,
        **logic_result,
    }
    if result_errors:
        response["warnings"] = result_errors
    return response


def get_dashboard():
    """Load the saved dashboard through the data manager."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return data_manager.load_plan()


def process_request_text(request_text):
    """Convert one frontend JSON line into one backend JSON line."""
    try:
        frontend_request = json.loads(request_text)
    except json.JSONDecodeError:
        error_response = {
            "ok": False,
            "errors": ["Backend input must be valid JSON."],
        }
        return json.dumps(error_response)

    if not isinstance(frontend_request, dict):
        error_response = {
            "ok": False,
            "errors": ["Backend input must be a JSON object."],
        }
        return json.dumps(error_response)

    data_payload = frontend_request.get("data_payload")
    if data_payload is None:
        data_payload = frontend_request

    repeating_schedule_data = frontend_request.get("repeating_schedule_data")
    result = process_request(
        data_payload,
        repeating_schedule_data=repeating_schedule_data,
    )
    return json.dumps(result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    backend_host = os.getenv("BACKEND_HOST", "0.0.0.0")
    backend_port_text = os.getenv("BACKEND_PORT", "8000")
    backend_port = int(backend_port_text)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((backend_host, backend_port))
    server_socket.listen()

    # TCP transport: accept one JSON request and return one JSON response.
    while True:
        client_socket, _client_address = server_socket.accept()
        with client_socket:
            client_file = client_socket.makefile("rwb")
            request_bytes = client_file.readline()
            if not request_bytes:
                continue

            request_text = request_bytes.decode("utf-8")
            response_text = process_request_text(request_text)
            response_line = response_text + "\n"
            response_bytes = response_line.encode("utf-8")

            client_file.write(response_bytes)
            client_file.flush()
