#!/bin/sh

# Run one representative module to limit live Qwen token usage.
set -eu

docker compose run --rm stackplan /input/test_payload_quick.json
