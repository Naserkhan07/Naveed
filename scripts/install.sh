#!/usr/bin/env sh
# Naveed installer for Linux and macOS.
#
#   curl -sSL https://raw.githubusercontent.com/Naserkhan07/Naveed/main/scripts/install.sh | sh
#
# It installs Naveed into its own virtual environment under ~/.naveed/venv, so it
# never fights with the system Python or an existing project.  Pass --all to also
# install the optional offline voice stack (a few hundred MB of models).
set -eu

ASK_ALL=0
for arg in "$@"; do
  case "$arg" in
    --all) ASK_ALL=1 ;;
    --help|-h)
      echo "usage: install.sh [--all]"
      echo "  --all   also install the offline speech stack (faster-whisper, piper)"
      exit 0
      ;;
  esac
done

HOME_DIR="${NAVEED_HOME:-$HOME/.naveed}"
VENV="$HOME_DIR/venv"
PY="${PYTHON:-python3}"

echo "Naveed installer"
echo "  home: $HOME_DIR"

command -v "$PY" >/dev/null 2>&1 || { echo "python3 was not found on PATH" >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "Naveed needs Python 3.9 or newer" >&2; exit 1; }

mkdir -p "$HOME_DIR"
if [ ! -d "$VENV" ]; then
  echo "  creating virtual environment…"
  "$PY" -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
NAVEED="$VENV/bin/naveed"

echo "  installing Naveed…"
"$PIP" install --quiet --upgrade pip
"$PIP" install --quiet "naveed[ui,capture,input]"
if [ "$ASK_ALL" = "1" ]; then
  echo "  installing the offline voice stack (this can take a while)…"
  "$PIP" install --quiet "naveed[voice]"
fi

echo "  writing a starter configuration…"
"$NAVEED" --setup --force >/dev/null 2>&1 || true

echo
echo "Done. Start the companion with:"
echo "  $NAVEED"
echo
echo "Naveed thinks with an LLM *API*: a URL and a model name. There is no key to"
echo "paste anywhere — the starter config points at a local Ollama on this machine:"
echo
echo "  ollama serve && ollama pull qwen2.5vl:7b      # the local default, nothing"
echo "                                                # leaves your PC"
echo
echo "Any other OpenAI-compatible API works too:"
echo "  $NAVEED --api http://127.0.0.1:1234/v1 --model qwen2.5-vl-7b-instruct"
echo "  $NAVEED --setup --provider openai     # a hosted one (LLM_TOKEN covers the"
echo "                                        # rare gateway that insists)"
echo "  $NAVEED --setup --provider ollama     # local, free, no token at all"
echo
echo "Prefer a text box, or no window at all? The same bot runs in your browser:"
echo "  $NAVEED --serve                    # http://127.0.0.1:8765 (no PySide6 needed)"
echo
echo "Check everything at any time with:"
echo "  $NAVEED --check"
echo "  $NAVEED --portrait ~/naveed.png    # see the mascot without starting it"
