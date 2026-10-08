#!/usr/bin/env bash
set -euo pipefail

# Use the OS trust store so uv can reach PyPI behind enterprise proxies.
export UV_NATIVE_TLS=1

command -v uv >/dev/null 2>&1 || { echo "ERROR: uv is not installed. See https://docs.astral.sh/uv/"; exit 1; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/dist}"

[[ -f "$REPO_ROOT/src/panoply/__main__.py" ]] || { echo "ERROR: src/panoply/__main__.py not found at $REPO_ROOT"; exit 1; }

echo "==> Building panoply binary with PyInstaller (Linux)..."

mkdir -p "$OUT_DIR"

# Code mode spawns pydantic-monty's `monty` worker executable, which the
# pydantic-monty-runtime wheel installs into the venv's scripts directory.
# Bundle it; scripts/pyinstaller_monty_hook.py points MONTY_BIN at it.
MONTY_BIN_PATH="$(uv run python -c 'import sysconfig; print(sysconfig.get_path("scripts"))')/monty"
[[ -x "$MONTY_BIN_PATH" ]] || { echo "ERROR: monty worker binary not found at $MONTY_BIN_PATH"; exit 1; }

uv run --with 'pyinstaller==6.19.0' pyinstaller \
  --onefile \
  --name panoply \
  --distpath "$OUT_DIR" \
  --workpath /tmp/panoply-pyinstaller-build \
  --specpath /tmp/panoply-pyinstaller-spec \
  --clean \
  --copy-metadata fastmcp \
  --copy-metadata mcp \
  --copy-metadata anyio \
  --copy-metadata httpx2 \
  --copy-metadata pydantic \
  --copy-metadata starlette \
  --copy-metadata uvicorn \
  --copy-metadata textual \
  --copy-metadata pydantic-monty \
  --hidden-import pydantic_monty \
  --hidden-import pydantic_monty._binary \
  --add-binary "$MONTY_BIN_PATH:." \
  --runtime-hook "$REPO_ROOT/scripts/pyinstaller_monty_hook.py" \
  "$REPO_ROOT/src/panoply/__main__.py"

echo "==> Done. Binary at: $OUT_DIR/panoply"
ls -lh "$OUT_DIR/panoply"
