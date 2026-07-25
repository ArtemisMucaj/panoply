"""Tools as discovered on a backend server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDescriptor:
    """A tool as reported by a backend, with its server prefix removed."""

    name: str
    description: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ToolDescriptor:
        return cls(payload["name"], payload.get("description") or "")

    def to_payload(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description}
