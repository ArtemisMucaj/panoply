"""Environment-variable placeholders inside server settings.

A server entry may reference the ambient environment with ``${VAR}``::

    {"command": "gitlab-mcp", "env": {"TOKEN": "${GITLAB_TOKEN}"}}

Resolution is a pure function of the template and the environment mapping the
caller supplies — the domain never reads ``os.environ`` itself.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


def expand_placeholders(value: str, environment: Mapping[str, str]) -> str:
    """Replace every ``${VAR}`` in *value* with its value in *environment*.

    Unknown variables are left verbatim so a misconfigured server fails with a
    readable ``${MISSING_TOKEN}`` rather than a silently empty credential.
    """
    return PLACEHOLDER.sub(lambda m: environment.get(m.group(1), m.group(0)), value)


def expand_mapping(
    values: Mapping[str, Any], environment: Mapping[str, str]
) -> dict[str, Any]:
    """Expand placeholders in every string value of *values*."""
    return {
        key: expand_placeholders(value, environment) if isinstance(value, str) else value
        for key, value in values.items()
    }
