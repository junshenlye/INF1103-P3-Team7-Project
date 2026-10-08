"""Command-line entry point for file intake."""

import logging

from . import io_manager


def main(argv=None):
    """Pass the payload and collected errors through the manager chain."""
    errors = []

    cli_input = io_manager.parse_cli_arguments(argv)
    payload, io_errors = io_manager.process_cli_input(cli_input)
    errors.extend(io_errors)

    # Future managers receive payload and append their errors here.
    print(payload, errors)


if __name__ == "__main__":
    # Enable progress logs produced by each manager during CLI execution.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
