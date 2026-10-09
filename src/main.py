"""Command-line entry point for the IO-to-AI pipeline."""

import asyncio
import json
import logging

from . import ai_manager, io_manager


LOGGER = logging.getLogger(__name__)


def main(argv=None):
    """Run IO then AI, print one JSON result and return ``(payload, errors)``.

    Main only coordinates managers. It passes the same hard-error list forward
    and leaves soft AI issues inside each module's ``follow_ups`` metadata.
    """
    LOGGER.info("Pipeline started")

    cli_input = io_manager.parse_cli_arguments(argv)
    payload, errors = io_manager.process_cli_input(cli_input)
    if payload is None:
        LOGGER.warning(
            "Pipeline stopped after IO Manager with %d hard error(s)",
            len(errors),
        )
    else:
        # AI Manager appends only hard failures to the existing error list.
        payload, errors = asyncio.run(ai_manager.process_payload(payload, errors))
        if payload is None:
            LOGGER.warning(
                "Pipeline stopped after AI Manager with %d hard error(s)",
                len(errors),
            )
        else:
            log_result = LOGGER.warning if errors else LOGGER.info
            log_result(
                "Pipeline completed with %d module(s) and %d hard error(s)",
                payload["module_count"],
                len(errors),
            )

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
