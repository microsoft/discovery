#!/bin/sh
set -e
# /input is caller-owned and never created or modified by the worker.
mkdir -p /output /workdir
exec "$@"
