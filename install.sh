#!/usr/bin/env bash
# One-step setup of instagram-campaign-mcp on a new macOS / Linux machine.
#
#   ./install.sh                       # install, create .env, write mcp-config.json
#   ./install.sh --dev                 # + test dependencies and run the tests
#   ./install.sh --register-claude-code  # + `claude mcp add` (user scope)
#   ./install.sh --name ig             # MCP server name (default: instagram)
#
# Uses uv if installed (it fetches Python 3.12 if needed), otherwise any
# installed Python 3.10+. Safe to re-run; never overwrites .env.
set -euo pipefail

# pwd -W gives a native C:/... path under Git Bash on Windows (uv/pip can't
# resolve MSYS paths like /tmp/...); elsewhere it fails and pwd is used.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
NAME="instagram"
DEV=0
REGISTER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dev) DEV=1 ;;
    --register-claude-code) REGISTER=1 ;;
    --name) NAME="$2"; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }

VENV="$ROOT/.venv"
# Git Bash on Windows uses Scripts/ and .exe; everything else bin/.
if [ -d "$VENV/Scripts" ] || { [ ! -d "$VENV" ] && [ -n "${WINDIR:-}" ]; }; then
  BIN="$VENV/Scripts"; EXE=".exe"
else
  BIN="$VENV/bin"; EXE=""
fi
PY="$BIN/python$EXE"
TARGET="$ROOT"
[ "$DEV" = 1 ] && TARGET="$ROOT[dev]"

if [ -x "$PY" ] && ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo "Existing .venv uses Python < 3.10. Delete .venv and re-run." >&2
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  step "Installing with uv"
  [ -x "$PY" ] || uv venv --seed "$VENV" --python 3.12
  uv pip install --python "$PY" -e "$TARGET"
elif [ -x "$PY" ]; then
  step "Updating existing .venv"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -e "$TARGET"
else
  PYTHON=""
  for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1 &&
       "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      PYTHON="$cand"; break
    fi
  done
  if [ -z "$PYTHON" ]; then
    echo "No Python 3.10+ found. Install uv (curl -LsSf https://astral.sh/uv/install.sh | sh)" >&2
    echo "or Python 3.12, then re-run this script." >&2
    exit 1
  fi
  step "Installing with $PYTHON"
  [ -x "$PY" ] || "$PYTHON" -m venv "$VENV"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -e "$TARGET"
fi

(cd "$ROOT" && "$PY" -c "import src.instagram_mcp_server")

if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/env.example" "$ROOT/.env"
  step "Created .env from env.example"
fi

SERVER="$BIN/ig-campaign-mcp$EXE"
"$PY" - "$ROOT/mcp-config.json" "$NAME" "$SERVER" <<'PYEOF'
import json, sys
path, name, server = sys.argv[1:4]
with open(path, "w", encoding="utf-8") as f:
    json.dump({"mcpServers": {name: {"command": server}}}, f, indent=2)
    f.write("\n")
PYEOF
step "Wrote mcp-config.json"

if [ "$REGISTER" = 1 ]; then
  if command -v claude >/dev/null 2>&1; then
    step "Registering '$NAME' with Claude Code (user scope)"
    claude mcp add --scope user "$NAME" -- "$SERVER" ||
      echo "claude mcp add failed. If '$NAME' already exists: claude mcp remove $NAME --scope user, then re-run." >&2
  else
    echo "Claude Code CLI ('claude') not found on PATH; skipped registration." >&2
  fi
fi

if [ "$DEV" = 1 ]; then
  step "Running tests"
  (cd "$ROOT" && "$PY" -m pytest -q)
fi

echo
printf '\033[32mDone.\033[0m\n'
if grep -Eq '^INSTAGRAM_ACCESS_TOKEN=(your_long_lived_access_token)?[[:space:]]*$' "$ROOT/.env"; then
  echo "Next: edit .env and set INSTAGRAM_ACCESS_TOKEN (and INSTAGRAM_BUSINESS_ACCOUNT_ID)."
fi
# ffmpeg renders and probes the videos; we print the command instead of running sudo.
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  case "$(uname -s)" in
    Darwin)               FFMPEG_CMD="brew install ffmpeg" ;;
    MINGW*|MSYS*|CYGWIN*) FFMPEG_CMD="winget install --id Gyan.FFmpeg -e" ;;
    *)                    FFMPEG_CMD="sudo apt install ffmpeg (or your package manager)" ;;
  esac
  echo "Next: install ffmpeg (video rendering): $FFMPEG_CMD"
fi
echo "MCP server:      $SERVER"
echo "Claude Code:     claude mcp add --scope user $NAME -- \"$SERVER\""
case "$(uname -s)" in
  Darwin) DESKTOP="$HOME/Library/Application Support/Claude/claude_desktop_config.json" ;;
  *)      DESKTOP="your Claude Desktop claude_desktop_config.json" ;;
esac
echo "Claude Desktop:  merge mcp-config.json into $DESKTOP"
echo "Scheduler:       $BIN/ig-campaign$EXE daemon"
