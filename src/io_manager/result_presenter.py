"""JSON and terminal output boundary."""

import json
import sys


class ResultPresenter:
    def display(self, payload, errors):
        print(json.dumps({"payload": payload, "errors": errors}, indent=2))

    def message(self, message, error=False, end="\n"):
        print(message, file=sys.stderr if error else sys.stdout, end=end)
