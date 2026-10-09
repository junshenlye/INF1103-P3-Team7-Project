"""Command-line entry point for the IO-to-AI pipeline."""

import asyncio
import json
import logging

from . import ai_manager, io_manager


LOGGER = logging.getLogger(__name__)


async def run_pipeline(argv=None):
    """Run IO then AI and return their final ``(payload, errors)``.

    Main only coordinates managers; it does not repeat their validation. The
    same hard-error list is passed forward, while AI soft issues remain inside
    each module's ``follow_ups`` metadata.
    """
    LOGGER.info("Pipeline started")

    cli_input = io_manager.parse_cli_arguments(argv)
    payload, errors = io_manager.process_cli_input(cli_input)
    if payload is None:
        LOGGER.warning(
            "Pipeline stopped after IO Manager with %d hard error(s)",
            len(errors),
        )
        return None, errors

    # AI Manager owns AI validation and keeps soft issues inside module
    # follow_ups. Only hard failures are appended to this same error list.
    payload, errors = await ai_manager.process_payload(payload, errors)
    if payload is None:
        LOGGER.warning(
            "Pipeline stopped after AI Manager with %d hard error(s)",
            len(errors),
        )
        return None, errors

    log_result = LOGGER.warning if errors else LOGGER.info
    log_result(
        "Pipeline completed with %d module(s) and %d hard error(s)",
        payload["module_count"],
        len(errors),
    )
    return payload, errors


def main(argv=None):
    """Run the pipeline, print one machine-readable JSON result and return it.

    Returning the tuple keeps the entry point simple to test or reuse.
    """
    payload, errors = asyncio.run(run_pipeline(argv))
    print(
        json.dumps(
            {"payload": payload, "errors": errors},
            indent=2,
        )
    )
    return payload, errors


if __name__ == "__main__":
    # Enable progress logs produced by each manager during CLI execution.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
