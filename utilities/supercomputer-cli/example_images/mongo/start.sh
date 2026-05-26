#!/usr/bin/env bash
set -euo pipefail

# Minimal startup script: provide Mongo connection string and launch run.py
# Usage: start.sh <mongo-connection-string> [additional args passed to Python]

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  echo "Usage: $0 <mongo-connection-string> [extra-args]"
  echo "Example: $0 mongodb+srv://user:pass@cluster.mongodb.net/mydb"
  exit 0
fi

if [[ $# -lt 1 ]]; then
  echo "Error: Mongo connection string required" >&2
  echo "Run with --help for usage." >&2
  exit 1
fi

export MONGO_URI="$1"
shift || true

echo "Starting Mongo client app with MONGO_URI (redacted): ${MONGO_URI%%:*}://<redacted>@..."
exec python3 run.py "$@"
