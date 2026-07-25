#!/usr/bin/env bash
set -euo pipefail

# Use the OS trust store (macOS Keychain / Windows cert store) so uv can
# reach PyPI behind enterprise proxies like Zscaler.
export UV_NATIVE_TLS=1

command -v uv >/dev/null 2>&1 || { echo "ERROR: uv is not installed. See https://docs.astral.sh/uv/"; exit 1; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/dist}"

[[ -f "$REPO_ROOT/src/panoply/__main__.py" ]] || { echo "ERROR: src/panoply/__main__.py not found at $REPO_ROOT"; exit 1; }

echo "==> Building panoply binary with PyInstaller (macOS)..."

mkdir -p "$OUT_DIR"

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
  --copy-metadata httpx \
  --copy-metadata pydantic \
  --copy-metadata starlette \
  --copy-metadata uvicorn \
  --copy-metadata textual \
  --copy-metadata pydantic-monty \
  --hidden-import pydantic_monty \
  "$REPO_ROOT/src/panoply/__main__.py"

echo "==> Done. Binary at: $OUT_DIR/panoply"
ls -lh "$OUT_DIR/panoply"
