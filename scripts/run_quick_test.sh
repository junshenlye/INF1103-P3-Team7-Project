#!/bin/sh

# Run one representative module to limit live Qwen token usage.
set -eu

docker compose run --rm stackplan-cli /input/test_payload_quick.json
