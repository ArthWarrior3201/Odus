#!/bin/sh
# Odus launcher for macOS and Linux (also works in Git Bash on Windows)
SELF="$0"
while [ -L "$SELF" ]; do
  LINK="$(readlink "$SELF")"
  case "$LINK" in /*) SELF="$LINK" ;; *) SELF="$(dirname "$SELF")/$LINK" ;; esac
done
DIR="$(cd "$(dirname "$SELF")" && pwd)"
if python3 -c "" >/dev/null 2>&1; then PY=python3; else PY=python; fi
exec "$PY" "$DIR/odus.py" "$@"
