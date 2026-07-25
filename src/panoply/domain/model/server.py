"""A single backend MCP server the proxy fans out to."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

ENABLED_KEY = "enabled"
DISABLED_TOOLS_KEY = "disabledTools"
DESCRIPTION_KEY = "description"
AUTH_KEY = "auth"
ENV_KEY = "env"
URL_KEY = "url"

OAUTH = "oauth"

#: Keys Panoply layers on top of the standard MCP server-config schema.  They
#: are stripped before an entry is handed to an MCP client library, which would
#: otherwise reject them.
NON_STANDARD_KEYS = frozenset({ENABLED_KEY, DISABLED_TOOLS_KEY})


@dataclass(frozen=True)
class ServerDefinition:
    """One entry under ``mcpServers``, named and interpreted.

    The raw settings dict is kept verbatim so unknown fields survive a
    load/save round-trip; the properties give the rest of the system a typed
    reading of the handful of fields Panoply actually acts on.

    Instances are immutable: the ``with_*`` methods return a new definition.
    """

    name: str
    settings: Mapping[str, Any] = field(default_factory=dict)

    # ── Interpretation ────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """True unless the entry carries an explicit ``"enabled": false``."""
        return self.settings.get(ENABLED_KEY, True) is not False

    @property
    def description(self) -> str:
        """One-line summary of what this backend is for (may be empty).

        Surfaced to agents by the ``load_tools`` overview so they can pick an
        area before searching for a specific tool.
        """
        value = self.settings.get(DESCRIPTION_KEY)
        return value.strip() if isinstance(value, str) else ""

    @property
    def disabled_tools(self) -> tuple[str, ...]:
        """Bare tool names the user has switched off on this server."""
        return tuple(self.settings.get(DISABLED_TOOLS_KEY) or ())

    @property
    def uses_oauth(self) -> bool:
        return self.settings.get(AUTH_KEY) == OAUTH

    @property
    def url(self) -> str:
        value = self.settings.get(URL_KEY)
        return value if isinstance(value, str) else ""

    @property
    def environment(self) -> Mapping[str, Any] | None:
        value = self.settings.get(ENV_KEY)
        return value if isinstance(value, Mapping) else None

    @property
    def transport_settings(self) -> dict[str, Any]:
        """The entry as an MCP client library expects it — extras removed."""
        return {k: v for k, v in self.settings.items() if k not in NON_STANDARD_KEYS}

    # ── Tool naming ───────────────────────────────────────────────────────────

    def qualify(self, tool: str) -> str:
        """Namespace a bare tool name the way the proxy exposes it."""
        return f"{self.name}_{tool}"

    def owns(self, qualified_tool: str) -> bool:
        """True when *qualified_tool* was contributed by this server."""
        return qualified_tool.startswith(f"{self.name}_")

    def qualified_disabled_tools(self) -> frozenset[str]:
        return frozenset(self.qualify(tool) for tool in self.disabled_tools)

    # ── Transitions ───────────────────────────────────────────────────────────

    def with_enabled(self, enabled: bool) -> ServerDefinition:
        """Switch the whole server on or off.

        Enabling drops the key entirely rather than writing ``true``: enabled
        is the default, and a minimal config is easier to hand-edit.
        """
        settings = dict(self.settings)
        if enabled:
            settings.pop(ENABLED_KEY, None)
        else:
            settings[ENABLED_KEY] = False
        return ServerDefinition(self.name, settings)

    def with_tool_enabled(self, tool: str, enabled: bool) -> ServerDefinition:
        """Switch a single tool on or off. Idempotent in both directions."""
        disabled = [t for t in self.disabled_tools if t != tool]
        if not enabled:
            disabled.append(tool)
        settings = dict(self.settings)
        if disabled:
            settings[DISABLED_TOOLS_KEY] = disabled
        else:
            settings.pop(DISABLED_TOOLS_KEY, None)
        return ServerDefinition(self.name, settings)

    def with_disabled_tools(self, tools: frozenset[str] | set[str]) -> ServerDefinition:
        """Replace the disabled-tool set wholesale (used by the TUI on save)."""
        settings = dict(self.settings)
        if tools:
            settings[DISABLED_TOOLS_KEY] = sorted(tools)
        else:
            settings.pop(DISABLED_TOOLS_KEY, None)
        return ServerDefinition(self.name, settings)
