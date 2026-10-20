#!/bin/bash
set -e
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"
if [ -d "$SCRIPT_DIR/RGBTViewer.app" ]; then
  exec /usr/bin/open -n "$SCRIPT_DIR/RGBTViewer.app" --args "$@"
fi
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)'; then
  exec python3 "$SCRIPT_DIR/desktop.py" "$@"
fi
printf '%s\n' 'Python 3.9 or newer was not found.' 'Install Python, or use a published macOS portable package containing RGBTViewer.app.'
read -r -p 'Press Return to close. '
exit 1
