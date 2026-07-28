"""Structured JSON logging for AI-assisted debugging (issue #70).

The default text format (``%(asctime)s %(name)s %(levelname)s %(message)s``)
is preserved for human-readable operation; ``setup_logging`` swaps in
a JSON formatter when ``format="json"`` is requested. The JSON shape is
stable and self-describing::

    {"ts": 1234567890.123, "level": "INFO", "logger": "deckd.server",
     "msg": "focus -> firefox (layout=firefox)"}

Existing ``log.info("foo %s", bar)`` call sites are unchanged; the
JSON formatter records the rendered message but does not capture the
``%`` arguments as separate fields. That keeps the diff minimal — the
value here is machine-searchable, structured time stamps, and a
``logger`` field that a grep operator can filter on, not a complete
key/value re-shape of every log site.
"""
from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record.

    ``record.__dict__`` is the source; standard ``LogRecord`` fields are
    mapped to a stable set of output keys (``ts``, ``level``,
    ``logger``, ``msg``), and any extra fields attached via
    ``logger.info(..., extra={...})`` are merged in. Exceptions are
    serialised with ``format_exception``.
    """

    DEFAULT_KEYS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        ts = getattr(record, "created", None) or 0.0
        payload: dict[str, object] = {
            "ts": round(float(ts), 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        for key, value in record.__dict__.items():
            if key in self.DEFAULT_KEYS or key.startswith("_"):
                continue
            payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(
    *,
    level: int = logging.INFO,
    fmt: str = "text",
    stream: Iterable | None = None,
) -> None:
    """Install the deckd logging configuration.

    ``fmt="text"`` uses the same human-readable format as before
    (backward-compatible default). ``fmt="json"`` swaps the formatter
    on the root logger to :class:`JsonFormatter`. ``stream`` defaults
    to ``sys.stderr``; tests can pass an in-memory stream.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    target = stream if stream is not None else sys.stderr
    handler = logging.StreamHandler(target)  # type: ignore[arg-type]
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(level)