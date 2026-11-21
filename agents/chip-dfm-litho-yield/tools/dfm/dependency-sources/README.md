# Optional approved source cache

The build normally fetches official GitHub sources named by the adjacent lock.
It never uses a Python package index. For a build without GitHub access, place
approved archives here as `<name>-<full-commit>.tar.gz` and set the
`PYTHON_SOURCES_OFFLINE=1` build argument. Every archive must match the committed
SHA256. This only makes the Python-source installation offline; base image pulls
and operating-system packages still need their configured distribution sources.
Do not commit downloaded archives or proprietary files.