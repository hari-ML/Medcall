"""Logging setup: level from settings, request id available to all records."""

from __future__ import annotations

import logging
import sys

from .middleware import current_request_id

_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"


class _RequestIdFilter(logging.Filter):
    """Stamp every record with the current request id (or '-')."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        rid = current_request_id()
        record.request_id = rid if rid else "-"
        return True


_configured = False


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once; safe to call again to change the level."""
    global _configured
    root = logging.getLogger()
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        handler.addFilter(_RequestIdFilter())
        root.addHandler(handler)
        _configured = True
    root.setLevel(getattr(logging, level.strip().upper(), logging.INFO))
