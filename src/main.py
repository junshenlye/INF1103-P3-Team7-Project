"""Command-line entry point for file intake."""

from .io_manager import parse_cli_arguments, process_cli_input


def main(argv=None):
    pipeline_errors = []

    cli_input = parse_cli_arguments(argv)
    ai_payload, io_errors = process_cli_input(cli_input)
    pipeline_errors.extend(io_errors)

    # Future AI, Logic, and Data Manager stages append their errors here.
    return ai_payload, pipeline_errors


if __name__ == "__main__":
    main()
