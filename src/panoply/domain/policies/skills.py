"""Who gets to see skills.

Skills are mounted on the proxy unconditionally so that a single set of
backend subprocesses serves everyone, but most MCP clients have native skills
support and don't want them re-exposed as tools.  Clients that do need them
opt in per connection.
"""

from __future__ import annotations

#: Tools the skills provider contributes once resources are exposed as tools.
SKILL_TOOL_NAMES = frozenset({"list_resources", "read_resource"})

SKILL_RESOURCE_SCHEME = "skill://"

#: Query-parameter values that count as opting in.
AFFIRMATIVE = frozenset({"true", "1", "yes"})


def wants_skills(flag: str | None) -> bool:
    """True when a client asked for skills via ``?skills=<flag>``.

    A missing flag means no — the bare endpoint stays minimal.
    """
    return (flag or "").strip().lower() in AFFIRMATIVE


def is_skill_tool(name: str) -> bool:
    return name in SKILL_TOOL_NAMES


def is_skill_resource(uri: str) -> bool:
    return uri.startswith(SKILL_RESOURCE_SCHEME)
