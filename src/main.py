"""Command-line entry point for the manager pipeline."""

import asyncio
import logging
import os

from . import ai_manager, data_manager, io_manager, logic_manager


LOGGER = logging.getLogger(__name__)


def main(argv=None):
    """Run IO, AI, Logic and optional Data Manager persistence.

    Main only coordinates managers. It passes the same hard-error list forward
    and leaves soft issues as comment metadata on modules and schedule items.
    """
    LOGGER.info("Pipeline started")

    # Each manager returns None when the next manager must not run. Keeping the
    # same payload and error variables makes the hand-off visible and linear.
    current_stage = "IO Manager"
    cli_input = io_manager.parse_cli_arguments(argv)
    payload, errors = io_manager.process_cli_input(cli_input)

    # Persistence is optional for direct local scripts and enabled by Compose.
    # Database failures are flushed forward but do not discard an otherwise
    # usable assessment result.
    project_id = None
    run_id = None
    study_plan = None
    source_hashes = {}
    model_name = f"{ai_manager.RELEVANCE_MODEL}+{ai_manager.REASONING_MODEL}"
    if data_manager.is_configured():
        try:
            configured_project_id = os.getenv("STACKPLAN_PROJECT_ID")
            if configured_project_id is not None:
                configured_project_id = int(configured_project_id)
            project_name = os.getenv(
                "STACKPLAN_PROJECT_NAME",
                cli_input["payload_file"].stem,
            )
            project = data_manager.get_or_create_project(
                project_name,
                project_id=configured_project_id,
            )
            project_id = project["id"]
            requested_count = payload["module_count"] if payload else 0
            run_id = data_manager.start_pipeline_run(project_id, requested_count)
        except (ValueError, data_manager.DataManagerError) as error:
            errors.append(data_manager.format_data_error(error))

    if payload is not None:
        current_stage = "AI Manager"
        if project_id is not None:
            try:
                source_hashes = {
                    module["module_title"]: data_manager.hash_files(
                        module.get("stored_file_paths")
                        or [module["stored_file_path"]]
                    )
                    for module in payload["modules"]
                }
            except (OSError, data_manager.DataManagerError) as error:
                errors.append(data_manager.format_data_error(error))

        # Every submitted module goes through Qwen. Stored results are retained
        # for history only and never bypass the assignment's AI processing step.
        payload, errors = asyncio.run(
            ai_manager.process_payload(payload, errors)
        )

    if payload is not None:
        current_stage = "Logic Manager"
        payload, errors = logic_manager.process_payload(payload, errors)

    # Logic Manager's complete schedule becomes the reasoning context for one
    # automatic trimester plan. Failure keeps the factual schedule available.
    if payload is not None:
        current_stage = "AI Study Plan"
        study_preferences = logic_manager.normalize_study_preferences(
            logic_manager.DEFAULT_STUDY_PREFERENCES
        )
        raw_study_plan, errors = asyncio.run(
            ai_manager.process_recommendation(
                payload,
                logic_manager.DEFAULT_RECOMMENDATION_TYPE,
                study_preferences,
                errors,
            )
        )
        if raw_study_plan is not None:
            study_plan, errors = logic_manager.process_recommendation(
                raw_study_plan,
                logic_manager.DEFAULT_RECOMMENDATION_TYPE,
                payload,
                study_preferences,
                errors,
            )
        if study_plan is not None:
            payload = dict(payload)
            payload["study_plan"] = study_plan
            payload["study_preferences"] = study_preferences

    if run_id is not None:
        try:
            data_manager.save_pipeline_result(
                project_id,
                run_id,
                payload,
                errors,
                source_hashes=source_hashes,
                prompt_version=ai_manager.PROMPT_VERSION,
                model_name=model_name,
            )
        except data_manager.DataManagerError as error:
            errors.append(data_manager.format_data_error(error))

    if project_id is not None and study_plan is not None:
        try:
            data_manager.save_recommendation(
                project_id,
                logic_manager.DEFAULT_RECOMMENDATION_TYPE,
                payload["modules"],
                study_preferences,
                study_plan,
                ai_manager.RECOMMENDATION_PROMPT_VERSION,
                ai_manager.REASONING_MODEL,
            )
        except data_manager.DataManagerError as error:
            errors.append(data_manager.format_data_error(error))

    if payload is None:
        LOGGER.warning(
            "Pipeline stopped after %s with %d hard error(s)",
            current_stage,
            len(errors),
        )
    else:
        log_result = LOGGER.warning if errors else LOGGER.info
        log_result(
            "Pipeline completed with %d module(s) and %d hard error(s)",
            payload["module_count"],
            len(errors),
        )

    io_manager.display_pipeline_result(payload, errors)
    return payload, errors


if __name__ == "__main__":
    # Enable progress logs produced by each manager during CLI execution.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    final_payload, _ = main()
    if final_payload is None:
        raise SystemExit(1)
