"""Flask presentation server. All assessment logic remains behind the helper API."""

import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote

from flask import Flask, Response, jsonify, render_template, request


def create_app():
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        API_URL=os.getenv("STACKPLAN_API_URL", "http://127.0.0.1:8000").rstrip("/"),
        API_TIMEOUT=1860,
    )

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.route("/api/<path:resource>", methods=["GET", "POST", "PUT"])
    @app.get("/health")
    def proxy(resource=None):
        path = quote(request.path, safe="/")
        if request.query_string:
            path += "?" + request.query_string.decode("ascii")
        upstream_request = Request(
            app.config["API_URL"] + path,
            data=request.get_data() if request.method in {"POST", "PUT"} else None,
            headers={"Content-Type": request.content_type} if request.content_type else {},
            method=request.method,
        )
        try:
            with urlopen(upstream_request, timeout=app.config["API_TIMEOUT"]) as upstream:
                return Response(upstream.read(), status=upstream.status,
                                content_type=upstream.headers.get("Content-Type", "application/json"))
        except HTTPError as error:
            return Response(error.read(), status=error.code,
                            content_type=error.headers.get("Content-Type", "application/json"))
        except (URLError, TimeoutError, OSError):
            return jsonify(payload=None, errors=["The helper API is unavailable. Start the API and database, then retry."]), 502

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(payload=None, errors=["The upload exceeds the 50 MB limit."]), 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5173")), threaded=True)
