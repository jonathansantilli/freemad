from __future__ import annotations

import json
import logging
import tempfile

from freemad import Config, ConfigError
from freemad.config import load_config
from freemad.utils.logger import get_logger, log_event, RedactionFilter
from freemad.types import LogEvent


def _fresh_logger(cfg: Config) -> logging.Logger:
    logger = logging.getLogger("freemad")
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logger.setLevel(logging.NOTSET)
    return get_logger(cfg)


def test_structured_logging_and_redaction(tmp_path) -> None:
    log_file = tmp_path / "out.log"
    cfg = load_config(
        overrides={
            "logging": {"file": str(log_file), "structured": True, "console": False},
            "security": {"redact_patterns": ["secret"]},
        }
    )
    logger = _fresh_logger(cfg)
    log_event(logger, LogEvent.RUN_START, secret="secret123", visible="ok")
    text = log_file.read_text(encoding="utf-8")
    data = json.loads(text)
    # redaction filter should scrub "secret"
    assert "secret123" not in data["message"]
    assert "[REDACTED]" in data["message"]


def test_plain_logging_includes_event_label(tmp_path) -> None:
    log_file = tmp_path / "out.log"
    cfg = load_config(
        overrides={
            "logging": {"file": str(log_file), "structured": False, "console": False},
        }
    )
    logger = _fresh_logger(cfg)
    log_event(logger, LogEvent.RUN_START, run_id="abc")
    text = log_file.read_text(encoding="utf-8")
    assert "[run_start]" in text
    assert "run_id=abc" in text
