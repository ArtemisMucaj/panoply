"""Regenerate ``openapi.yaml`` from the FastAPI app.

    uv run python scripts/dump_openapi.py           # rewrite the file
    uv run python scripts/dump_openapi.py --check   # fail if it is stale

The spec is an artifact, not a source file: everything in it comes from the
models and docstrings in ``panoply.connector.http``.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import yaml

from panoply.connector.container import Container
from panoply.connector.http.api import create_api_app
from panoply.connector.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "openapi.yaml"

HEADER = """\
# Generated from the FastAPI app — do not edit by hand.
#
#   uv run python scripts/dump_openapi.py
#
# The source of truth is panoply/connector/http/{api,models}.py. A running
# server also serves this live at /openapi.json, with docs at /docs.
"""

#: Fixed so the generated document doesn't shift with whatever port the
#: generating process happened to pick.
DOCUMENTED_MCP_PORT = 7070


class SpecDumper(yaml.SafeDumper):
    """Renders the long markdown descriptions as readable literal blocks."""


def _block_scalars(dumper: yaml.SafeDumper, data: str):
    if "\n" in data and not any(line.rstrip() != line for line in data.splitlines()):
        # Trailing whitespace would force PyYAML to quote-and-escape instead.
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


SpecDumper.add_representer(str, _block_scalars)


def render() -> str:
    """Build the app in a throwaway data directory and dump its spec."""
    with tempfile.TemporaryDirectory() as scratch:
        settings = Settings(data_dir=Path(scratch) / "panoply", skill_dirs=())
        app = create_api_app(Container.build(settings), mcp_port=DOCUMENTED_MCP_PORT)
        spec = app.openapi()
    body = yaml.dump(
        spec, Dumper=SpecDumper, sort_keys=False, width=88, allow_unicode=True
    )
    return HEADER + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed spec is out of date",
    )
    args = parser.parse_args(argv)

    generated = render()
    if not args.check:
        SPEC_PATH.write_text(generated)
        print(f"wrote {SPEC_PATH.relative_to(REPO_ROOT)}")
        return 0

    current = SPEC_PATH.read_text() if SPEC_PATH.exists() else ""
    if current == generated:
        print(f"{SPEC_PATH.relative_to(REPO_ROOT)} is up to date")
        return 0
    print(
        f"{SPEC_PATH.relative_to(REPO_ROOT)} is out of date — "
        "run: uv run python scripts/dump_openapi.py",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
