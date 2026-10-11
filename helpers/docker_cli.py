"""Stage a payload safely and run Stackplan through Docker Compose."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def stage_payload(payload_path, staging_directory):
    """Copy a payload and its images into one Docker-readable directory."""
    payload_path = Path(payload_path).expanduser().resolve()
    staging_directory = Path(staging_directory)
    with payload_path.open("r", encoding="utf-8") as payload_stream:
        payload = json.load(payload_stream)
    modules = payload.get("modules")
    if not isinstance(modules, list) or not modules:
        raise ValueError("Payload must contain a non-empty modules array.")

    staged_modules = []
    for position, module in enumerate(modules):
        if not isinstance(module, dict) or not isinstance(module.get("file_path"), str):
            raise ValueError(f"Module at position {position} has no file_path.")
        source = Path(module["file_path"]).expanduser()
        if not source.is_absolute():
            source = payload_path.parent / source
        source = source.resolve()
        suffix = source.suffix.lower()
        staged_name = f"{uuid.uuid4().hex}{suffix}"
        shutil.copyfile(source, staging_directory / staged_name)
        staged_module = dict(module)
        staged_module["file_path"] = staged_name
        staged_modules.append(staged_module)

    staged_payload = {
        "module_count": len(staged_modules),
        "modules": staged_modules,
    }
    staged_path = staging_directory / "payload.json"
    with staged_path.open("w", encoding="utf-8") as output_stream:
        json.dump(staged_payload, output_stream, indent=2)
    return staged_path


def build_compose_command(staging_directory, project_id=None, project_name=None):
    """Return the argument-safe Compose command for one staged run."""
    command = [
        "docker",
        "compose",
        "run",
        "--rm",
        "--volume",
        f"{Path(staging_directory).resolve()}:/input:ro",
    ]
    if project_id is not None:
        command.extend(["--env", f"STACKPLAN_PROJECT_ID={project_id}"])
    if project_name:
        command.extend(["--env", f"STACKPLAN_PROJECT_NAME={project_name}"])
    command.extend(["stackplan-cli", "/input/payload.json"])
    return command


def run_docker_payload(payload_path, output_path=None, project_id=None, project_name=None):
    """Start PostgreSQL, run one staged payload and return the CLI JSON text."""
    subprocess.run(
        ["docker", "compose", "up", "--detach", "database"],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    with tempfile.TemporaryDirectory(prefix="stackplan-docker-") as temporary_path:
        staging_directory = Path(temporary_path)
        stage_payload(payload_path, staging_directory)
        completed = subprocess.run(
            build_compose_command(staging_directory, project_id, project_name),
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        if output_path is not None:
            Path(output_path).write_text(completed.stdout, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"Stackplan container stopped with exit code {completed.returncode}."
            )
        return completed.stdout


def main(argv=None):
    """Run the Docker helper from the command line."""
    parser = argparse.ArgumentParser(
        description="Stage module images and run Stackplan with Docker Compose."
    )
    parser.add_argument("payload_file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--project-name")
    arguments = parser.parse_args(argv)
    try:
        result = run_docker_payload(
            arguments.payload_file,
            arguments.output,
            arguments.project_id,
            arguments.project_name,
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        parser.error(str(error))
    if arguments.output is None:
        print(result, end="")


if __name__ == "__main__":
    main()
