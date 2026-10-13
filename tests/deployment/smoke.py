"""Black-box checks for a running Stackplan Docker deployment."""

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(url, method="GET", body=None):
    """Return ``(status, content_type, body)`` from one HTTP request."""
    encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    http_request = Request(url, data=encoded_body, headers=headers, method=method)
    with urlopen(http_request, timeout=5) as response:
        return (
            response.status,
            response.headers.get("Content-Type", ""),
            response.read().decode("utf-8"),
        )


def wait_for_healthy(url, service_name):
    """Wait briefly for one deployed service to report database-backed health."""
    last_error = None
    for _attempt in range(30):
        try:
            status, _content_type, content = request(url)
            payload = json.loads(content)
            if status == 200 and payload == {"status": "healthy"}:
                return
            last_error = RuntimeError(
                f"Unexpected health response: status={status}, payload={payload}"
            )
        except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
        time.sleep(1)
    raise RuntimeError(f"{service_name} did not become healthy: {last_error}")


def require(condition, message):
    """Raise a readable deployment failure when an observable outcome is absent."""
    if not condition:
        raise RuntimeError(message)


def main():
    """Verify health, frontend delivery and a database-backed API round trip."""
    api_url = os.getenv("STACKPLAN_DEPLOYMENT_API_URL", "http://127.0.0.1:18000")
    frontend_url = os.getenv(
        "STACKPLAN_DEPLOYMENT_FRONTEND_URL",
        "http://127.0.0.1:15173",
    )

    wait_for_healthy(f"{api_url}/health", "API")
    wait_for_healthy(f"{frontend_url}/health", "Frontend proxy")

    status, content_type, homepage = request(frontend_url)
    require(status == 200, "Frontend homepage did not return HTTP 200.")
    require("text/html" in content_type, "Frontend homepage was not HTML.")
    require("<title>Stackplan" in homepage, "Frontend homepage was not Stackplan.")

    status, _content_type, content = request(
        f"{frontend_url}/api/projects",
        method="POST",
        body={"name": "Deployment smoke test", "week_count": 14},
    )
    created = json.loads(content)
    require(status == 201, "Project creation did not return HTTP 201.")
    require(created.get("errors") == [], "Project creation returned errors.")
    project_id = created.get("payload", {}).get("id")
    require(type(project_id) is int, "Project creation returned no numeric ID.")

    status, _content_type, content = request(f"{frontend_url}/api/projects")
    projects = json.loads(content)
    require(status == 200, "Project listing did not return HTTP 200.")
    require(projects.get("errors") == [], "Project listing returned errors.")
    require(
        any(project.get("id") == project_id for project in projects.get("payload", [])),
        "The project written through the API was not read back from PostgreSQL.",
    )

    sys.stdout.write(
        "Deployment ready: database, API, frontend and persistence round trip passed.\n"
    )


if __name__ == "__main__":
    main()
