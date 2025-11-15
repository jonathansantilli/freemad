from __future__ import annotations

import json
import logging
from typing import Any, Dict

from freemad.security import Redactor
from freemad.config import Config
from freemad.types import LogEvent


class RedactionFilter(logging.Filter):
    def __init__(self, redactor: Redactor):
        super().__init__()
        self.redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover trivial
        if isinstance(record.msg, str):
            record.msg = self.redactor.redact(record.msg)
        return True


def get_logger(cfg: Config) -> logging.Logger:
    logger = logging.getLogger("freemad")
    if logger.handlers:
        return logger
    level = getattr(logging, cfg.logging.level, logging.INFO)
    logger.setLevel(level)
    redactor = Redactor(cfg.security.redact_patterns)
    flt = RedactionFilter(redactor)

    if cfg.logging.console:
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.addFilter(flt)
        if cfg.logging.structured:
            ch.setFormatter(_JsonFormatter())
        else:
            ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(ch)
    if cfg.logging.file:
        fh = logging.FileHandler(cfg.logging.file)
        fh.setLevel(level)
        fh.addFilter(flt)
        fh.setFormatter(_JsonFormatter() if cfg.logging.structured else logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    return logger


class _JsonFormatter(logging.Formatter):  # pragma: no cover minimal
    def format(self, record: logging.LogRecord) -> str:
        obj: Dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        return json.dumps(obj)


def log_event(logger: logging.Logger, event: LogEvent, level: int = logging.INFO, **fields: Any) -> None:
    if any(isinstance(h.formatter, _JsonFormatter) for h in logger.handlers):
        msg = json.dumps({"event": event.value, **fields})
    else:
        kv = " ".join(f"{k}={v}" for k, v in fields.items())
        msg = f"[{event.value}] {kv}" if kv else f"[{event.value}]"
    logger.log(level, msg)
