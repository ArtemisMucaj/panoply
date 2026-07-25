"""Structured logging setup.

All output goes to stderr; a supervising app (the macOS menu bar app, systemd)
captures it.  JSON is the default so Panoply and FastMCP emit the same shape.
"""

from __future__ import annotations

import datetime
import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        timestamp = (
            datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            + "Z"
        )
        data: dict = {
            "ts": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.message,
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    """Install the JSON stderr handler unless the host already set one up."""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
