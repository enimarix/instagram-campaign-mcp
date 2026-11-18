#!/usr/bin/env bash
# One-command setup of the studio on macOS / Linux (also runs under Git Bash).
#
#   ./install.sh                         # everything below except the OS schedule
#   ./install.sh --schedule              # + start `up` at reboot and the daily agent runs (crontab)
#   ./install.sh --dev                   # + test dependencies and run the tests
#   ./install.sh --register-claude-code  # + `claude mcp add` (user scope) for your own sessions
#   ./install.sh --name ig               # MCP server name (default: instagram)
#
# Steps: Python venv + package, .env (never overwritten), mcp-config.json, website
# build, motion packages, Reel downloader, then `ig-campaign doctor` (ffmpeg, Claude
# Code, ...). Safe to re-run: it upgrades what is there and skips what is done.
# System tools (ffmpeg, Node.js, git) are never installed for you: it says how.
set -euo pipefail

# pwd -W gives a native C:/... path under Git Bash on Windows (uv/pip can't
# resolve MSYS paths like /tmp/...); elsewhere it fails and pwd is used.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd; })"
NAME="instagram"
DEV=0
REGISTER=0
SCHEDULE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dev) DEV=1 ;;
    --register-claude-code) REGISTER=1 ;;
    --schedule) SCHEDULE=1 ;;
    --name) NAME="$2"; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

FAILED=0
step() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m✔\033[0m %s\n' "$*"; }
fail() { printf '\033[31m✖\033[0m %s\n    -> %s\n' "$1" "$2"; FAILED=1; }

VENV="$ROOT/.venv"
# Git Bash on Windows uses Scripts/ and .exe; everything else bin/.
if [ -d "$VENV/Scripts" ] || { [ ! -d "$VENV" ] && [ -n "${WINDIR:-}" ]; }; then
  BIN="$VENV/Scripts"; EXE=".exe"
else
  BIN="$VENV/bin"; EXE=""
fi
PY="$BIN/python$EXE"
IGC="$BIN/ig-campaign$EXE"
# The download extra (yt-dlp fallback) only installs on Python 3.11+ (marker in pyproject).
TARGET="$ROOT[download]"
[ "$DEV" = 1 ] && TARGET="$ROOT[dev,download]"

# --- 1. Python ------------------------------------------------------------
# The only step that stops the script: nothing else works without it.
step "Python environment and package"
if [ -x "$PY" ] && ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo "Existing .venv uses Python < 3.10. Delete .venv and re-run." >&2
  exit 1
fi
if command -v uv >/dev/null 2>&1; then
  [ -x "$PY" ] || uv venv --seed "$VENV" --python 3.12
  uv pip install --quiet --python "$PY" -e "$TARGET"
else
  if [ ! -x "$PY" ]; then
    PYTHON=""
    for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
      if command -v "$cand" >/dev/null 2>&1 &&
         "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        PYTHON="$cand"; break
      fi
    done
    if [ -z "$PYTHON" ]; then
      echo "✖ No Python 3.10+ found." >&2
      echo "    -> install uv (curl -LsSf https://astral.sh/uv/install.sh | sh) or Python 3.12, then re-run." >&2
      exit 1
    fi
    "$PYTHON" -m venv "$VENV"
  fi
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -e "$TARGET"
fi
(cd "$ROOT" && "$PY" -c "import src.instagram_mcp_server")
ok "Python $("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])') in .venv, package installed"

# --- 2. .env (never overwritten, never printed) --------------------------
step ".env"
if [ -f "$ROOT/.env" ]; then
  ok ".env already there (kept as it is)"
else
  cp "$ROOT/env.example" "$ROOT/.env"
  ok "created .env from env.example"
fi

# --- 3. MCP client config --------------------------------------------------
SERVER="$BIN/ig-campaign-mcp$EXE"
"$PY" - "$ROOT/mcp-config.json" "$NAME" "$SERVER" <<'PYEOF'
import json, sys
path, name, server = sys.argv[1:4]
with open(path, "w", encoding="utf-8") as f:
    json.dump({"mcpServers": {name: {"command": server}}}, f, indent=2)
    f.write("\n")
PYEOF
ok "wrote mcp-config.json (for Claude Desktop or any MCP client)"
if [ "$REGISTER" = 1 ]; then
  if ! command -v claude >/dev/null 2>&1; then
    fail "Claude Code registration" "install Claude Code first, then re-run with --register-claude-code"
  elif claude mcp add --scope user "$NAME" -- "$SERVER"; then
    ok "registered '$NAME' with Claude Code (user scope)"
  else
    fail "claude mcp add" "if '$NAME' already exists: claude mcp remove $NAME --scope user, then re-run"
  fi
fi

# --- 4. Website and motion packages (Node.js) -----------------------------
step "Website and motion packages"
if command -v npm >/dev/null 2>&1; then
  if (cd "$ROOT/web" && npm ci --silent && npm run build); then
    ok "website built (web/dist)"
  else
    fail "website build" "see the npm output above, then: npm --prefix web ci && npm --prefix web run build"
  fi
  if (cd "$ROOT/motion" && npm ci --silent); then
    ok "motion packages installed"
  else
    fail "motion packages" "see the npm output above, then: npm --prefix motion ci"
  fi
else
  fail "Node.js not found" "install Node.js 22.12+ (https://nodejs.org or your package manager), then re-run"
fi

# --- 5. Reel downloader ---------------------------------------------------
# Only when missing: a re-run must not undo `ig-campaign downloader update`.
step "Reel downloader"
DL="$ROOT/vendor/instagram-reels-downloader"
if [ ! -f "$DL/package.json" ]; then
  if command -v git >/dev/null 2>&1 &&
     git -C "$ROOT" submodule update --init vendor/instagram-reels-downloader; then
    ok "submodule checked out"
  else
    fail "downloader submodule" "needs git and a git clone: git submodule update --init vendor/instagram-reels-downloader"
  fi
fi
if [ -f "$DL/.next/BUILD_ID" ]; then
  ok "downloader already built (ig-campaign downloader update moves it to upstream's latest)"
elif [ -f "$DL/package.json" ]; then
  if (cd "$ROOT" && "$IGC" downloader setup >/dev/null); then
    ok "downloader built"
  else
    fail "downloader setup" "see the message above, then: ig-campaign downloader setup"
  fi
fi

# --- 6. Optional: tests, OS schedule -------------------------------------
if [ "$DEV" = 1 ]; then
  step "Tests"
  if (cd "$ROOT" && "$PY" -m pytest -q); then ok "tests pass"; else fail "tests" "see the pytest output above"; fi
fi
if [ "$SCHEDULE" = 1 ]; then
  step "OS schedule (crontab)"
  if (cd "$ROOT" && "$IGC" agent install-schedule); then
    ok "crontab block added (remove: ig-campaign agent install-schedule --remove)"
  else
    fail "agent install-schedule" "see the message above"
  fi
fi

# --- 7. Doctor: ffmpeg, Claude Code CLI, everything above -----------------
step "Checks (ig-campaign doctor, re-run it any time)"
(cd "$ROOT" && "$IGC" doctor) || FAILED=1

echo
if [ "$FAILED" = 1 ]; then
  printf '\033[33mAlmost done: fix the ✖ lines above, then re-run ./install.sh.\033[0m\n'
else
  printf '\033[32mDone.\033[0m\n'
fi
echo "Next:"
echo "  1. Fill in .env (INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID, ...): see README, Setup."
echo "  2. Start the studio:  $IGC up"
echo "  3. Open http://127.0.0.1:8765"
[ "$SCHEDULE" = 1 ] || echo "  4. To start it at reboot and run the agent every night: ./install.sh --schedule"
