"""Shared local/CI quality gate. Fast is offline; full also verifies real containers."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "test-results"


class Gate:
    def __init__(self, mode):
        self.mode = mode
        self.stage = "initialization"
        self.results = []
        self.env = dict(os.environ)
        for key in (
            "DATABASE_URL",
            "DASHSCOPE_API_KEY",
            "DASHSCOPE_BASE_URL",
            "STACKPLAN_PROJECT_ID",
            "STACKPLAN_PROJECT_NAME",
        ):
            self.env.pop(key, None)
        self.env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
        REPORTS.mkdir(exist_ok=True)
        if mode != "container":
            REPORTS.chmod(0o777)
        self.log = (REPORTS / f"{mode}.log").open("w", encoding="utf-8")

    def run(self, stage, command, timeout=300, extra_env=None):
        self.stage = stage
        print(f"\n[{self.mode}] {stage}", flush=True)
        self.log.write(f"\n[{self.mode}] {stage}\n")
        self.log.flush()
        start = time.monotonic()
        # A file avoids pipe deadlocks and keeps diagnostics even on interruption.
        with (REPORTS / f"{self.mode}-stage-{len(self.results) + 1}.log").open(
            "w+"
        ) as output:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env={**self.env, **(extra_env or {})},
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            try:
                status = process.wait(timeout=timeout)
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
            finally:
                output.seek(0)
                content = output.read()
                print(content, end="", flush=True)
                self.log.write(content)
                self.log.flush()
        self.results.append(
            {
                "stage": stage,
                "status": "passed" if status == 0 else "failed",
                "seconds": round(time.monotonic() - start, 2),
            }
        )
        if status:
            raise RuntimeError(f"{stage} exited with status {status}")

    def python_checks(self, integration=False):
        self.run(
            "Python static checks",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--no-cache",
                "src",
                "helpers",
                "frontend/app.py",
                "tests",
            ],
        )
        name = "docker" if integration else "offline"
        args = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--strict-markers",
            "--cov=src",
            "--cov=helpers",
            "--cov=frontend",
            "--cov-branch",
            "--cov-report=term:skip-covered",
            f"--cov-report=xml:{REPORTS / (name + '-coverage.xml')}",
            f"--cov-report=json:{REPORTS / (name + '-coverage.json')}",
            f"--junitxml={REPORTS / (name + '-tests.xml')}",
        ]
        if not integration:
            args += ["-m", "not integration"]
        self.run(
            "All Python tests in Docker" if integration else "Offline Python tests",
            args,
            extra_env={
                "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
                "STACKPLAN_REQUIRE_DATABASE": "1",
            }
            if integration
            else {},
        )
        self.coverage(name, integration)

    def coverage(self, name, integration):
        self.stage = "Coverage floors"
        data = json.loads((REPORTS / f"{name}-coverage.json").read_text())
        failures = []
        overall = data["totals"]["percent_covered"]
        floor = 80 if integration else 75
        if overall < floor:
            failures.append(f"overall coverage {overall:.1f}% < {floor}%")
        for package in (
            "domain",
            "application",
            "io_manager",
            "ai_manager",
            "logic_manager",
            "data_manager",
        ):
            if package == "data_manager" and not integration:
                continue
            summaries = [
                record["summary"]
                for path, record in data["files"].items()
                if path.startswith(f"src/{package}/")
                and not path.endswith("__init__.py")
            ]
            covered = sum(
                item["covered_lines"] + item["covered_branches"] for item in summaries
            )
            total = sum(
                item["num_statements"] + item["num_branches"] for item in summaries
            )
            percentage = 100 * covered / total if total else 0
            minimum = 75 if package == "data_manager" else 80
            if percentage < minimum:
                failures.append(f"{package} coverage {percentage:.1f}% < {minimum}%")
        if failures:
            raise RuntimeError("; ".join(failures))
        self.results.append(
            {
                "stage": "Coverage floors",
                "status": "passed",
                "percent": round(overall, 2),
            }
        )
        print(
            f"Coverage floors passed ({overall:.1f}% overall, statements and branches).",
            flush=True,
        )

    def javascript_checks(self):
        for script in ("app", "api", "model"):
            self.run(
                f"JavaScript syntax: {script}",
                ["node", "--check", f"frontend/static/{script}.js"],
            )
        self.run(
            "JavaScript contracts",
            [
                "node",
                "--test",
                "--test-reporter=spec",
                "--test-reporter=junit",
                "--test-reporter-destination=stdout",
                f"--test-reporter-destination={REPORTS / 'javascript-tests.xml'}",
                *map(str, sorted((ROOT / "tests/frontend").glob("*.test.mjs"))),
            ],
        )

    @contextmanager
    def containers(self):
        project = "stackplan-check-" + uuid.uuid4().hex[:10]
        compose = [
            "docker",
            "compose",
            "--env-file",
            os.devnull,
            "-p",
            project,
            "-f",
            "tests/deployment/compose.yaml",
        ]
        env = {
            "STACKPLAN_REPORTS": str(REPORTS),
            "STACKPLAN_API_PORT": "0",
            "STACKPLAN_FRONTEND_PORT": "0",
        }
        try:
            yield compose, env
        finally:
            # Best-effort diagnostics, mandatory cleanup. Never use the development compose file.
            with (REPORTS / f"{project}-docker.log").open("w") as output:
                try:
                    subprocess.run(
                        [*compose, "logs", "--no-color"],
                        cwd=ROOT,
                        env={**self.env, **env},
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        timeout=30,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired) as error:
                    output.write(f"Could not collect service diagnostics: {error}\n")
            cleanup = subprocess.run(
                [
                    *compose,
                    "down",
                    "--volumes",
                    "--remove-orphans",
                    "--rmi",
                    "local",
                    "--timeout",
                    "10",
                ],
                cwd=ROOT,
                env={**self.env, **env},
                stdout=self.log,
                stderr=subprocess.STDOUT,
                timeout=60,
                check=False,
            )
            if cleanup.returncode:
                raise RuntimeError(
                    "Disposable container cleanup failed; see test-results logs."
                )

    def integration(self):
        with self.containers() as (compose, env):
            self.run(
                "Build test containers",
                [*compose, "build", "--quiet", "tests", "node-tests"],
                600,
                env,
            )
            self.run(
                "Start disposable PostgreSQL",
                [
                    *compose,
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "60",
                    "test-database",
                ],
                90,
                env,
            )
            self.run(
                "Container static and Python checks",
                [*compose, "run", "--rm", "--no-TTY", "tests"],
                360,
                env,
            )
            self.run(
                "Container JavaScript checks",
                [*compose, "run", "--rm", "--no-TTY", "node-tests"],
                120,
                env,
            )

    def deployment(self):
        with self.containers() as (compose, env):
            self.run(
                "Build and start application containers",
                [
                    *compose,
                    "up",
                    "--build",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "90",
                    "api",
                    "frontend",
                ],
                600,
                env,
            )
            self.run(
                "Build application smoke client",
                [*compose, "build", "--quiet", "tests"],
                600,
                env,
            )
            self.run(
                "Application smoke and PostgreSQL round trip",
                [
                    *compose,
                    "run",
                    "--rm",
                    "--no-TTY",
                    "--entrypoint",
                    "python",
                    "tests",
                    "tests/deployment/smoke.py",
                ],
                180,
                env,
            )

    def close(self, success, error=None):
        summary = {
            "mode": self.mode,
            "status": "passed" if success else "failed",
            "stages": self.results,
        }
        if error:
            summary["error"] = str(error)
            summary["failed_stage"] = self.stage
        (REPORTS / f"{self.mode}-summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
        self.log.close()
        print(
            f"\n{self.mode.upper()} {'PASS' if success else 'FAIL'}; reports: {REPORTS}",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("fast", "full", "integration", "deployment", "container"),
        nargs="?",
        default="full",
    )
    mode = parser.parse_args().mode
    gate = Gate(mode)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if mode in {"fast", "full", "container"}:
            gate.python_checks(integration=mode == "container")
        if mode in {"fast", "full"}:
            gate.javascript_checks()
        if mode in {"full", "integration"}:
            gate.integration()
        if mode in {"full", "deployment"}:
            gate.deployment()
    except (Exception, KeyboardInterrupt) as error:
        print(f"FAIL during {gate.stage}: {error}", file=sys.stderr)
        gate.close(False, error)
        return 1
    gate.close(True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
