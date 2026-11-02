"""CLI presentation adapter for the shared planning application."""

import asyncio
import logging
import os
from pathlib import Path

from .io_manager import parse_cli_arguments, load_cli_payload, ResultPresenter
from .application.pipeline_result import PipelineResult
from .application.planning_service import create_service


def main(argv=None):
    path = Path(parse_cli_arguments(argv)["payload_file"]).expanduser().resolve()
    submission, errors = load_cli_payload(path)
    if errors:
        result = PipelineResult(None, errors)
    else:
        try:
            project_id = os.getenv("STACKPLAN_PROJECT_ID")
            project_id = int(project_id) if project_id is not None else None
            timeout = float(os.getenv("PIPELINE_TIMEOUT_SECONDS", "1800"))
            result = asyncio.run(
                create_service().run(
                    submission,
                    path.parent,
                    project_id,
                    os.getenv("STACKPLAN_PROJECT_NAME", path.stem),
                    timeout,
                )
            )
        except ValueError as error:
            result = PipelineResult(None, [f"Pipeline configuration error: {error}"])
    ResultPresenter().display(result.payload, list(result.errors))
    return result.payload, list(result.errors)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    final_payload, _ = main()
    if final_payload is None:
        raise SystemExit(1)
