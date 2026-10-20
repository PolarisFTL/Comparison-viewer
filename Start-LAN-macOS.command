#!/bin/bash
set -e
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec /bin/bash "$SCRIPT_DIR/Start-macOS.command" --lan "$@"
