#!/bin/bash
set -euo pipefail
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
