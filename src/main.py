"""Coordinate the IO, AI, logic, and data managers."""

from pathlib import Path

from dotenv import load_dotenv

from . import ai_manager, data_manager, io_manager, logic_manager


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def process_request(
    input_data,
    api_caller=None,
    current_date=None,
    repeating_schedule_data=None,
):
    """Coordinate the request from frontend input to the saved response.

    Flow: Frontend -> IO Manager -> AI Manager -> Logic Manager
          -> Data Manager -> Frontend response
    """
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    # IO Manager: validate the frontend payload and prepare the AI input.
    module_count = None
    if isinstance(input_data, dict):
        module_count = input_data.get("module_count")

    ai_input, errors = io_manager.prepare_ai_input(
        module_count,
        input_data,
        repeating_schedule_data,
    )
    if errors:
        return {"ok": False, "errors": errors}

    # AI Manager: interpret images, user context, and retry schedule context.
    ai_result = ai_manager.process(
        ai_input,
        api_caller=api_caller,
    )

    # Logic Manager: place extracted assessments into the trimester timeline.
    trimester_context = logic_manager.get_trimester_context(current_date)
    pacing_result = logic_manager.build_timeline(ai_result, trimester_context)

    # Data Manager: store the input, extraction, and completed timeline.
    saved = data_manager.save(
        input_data=ai_input,
        ai_result=ai_result,
        pacing_result=pacing_result,
    )
    if not saved:
        return {
            "ok": False,
            "errors": ["The trimester pacing result could not be saved."],
        }

    # Response: report the extraction count and completed pacing result.
    extracted_count = 0
    for module in ai_result["modules"]:
        module_assessments = module["assessments"]
        assessment_count = len(module_assessments)
        extracted_count += assessment_count

    return {
        "ok": True,
        "extracted_count": extracted_count,
        "models_used": ai_result.get("models_used", []),
        **pacing_result,
    }


def get_dashboard():
    """Load the saved dashboard through the data manager."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return data_manager.load_plan()
