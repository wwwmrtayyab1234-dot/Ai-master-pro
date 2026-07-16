"""Central crash capture with local, redacted, rotating log files."""

from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import sys
import threading
import traceback
from types import TracebackType
from typing import Any


_ACTIVE_PROTECTOR: "CrashProtector | None" = None

_SECRET_PATTERNS = (
    re.compile(r"\b(?:gsk|sk)_[A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"
    ),
    re.compile(
        r"(?i)((?:api[_ -]?key|client[_ -]?secret|refresh[_ -]?token)"
        r"\s*[:=]\s*)[^\s,;]+"
    ),
)


def redact_secrets(value: object) -> str:
    """Remove common API credentials before writing diagnostic text to disk."""
    redacted = str(value)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class CrashProtector:
    """Capture uncaught Python, thread, asyncio and Flet event failures.

    Logs stay on the user's device and rotate automatically so an error cannot
    grow the file forever. The service deliberately avoids provider secrets.
    """

    def __init__(
        self,
        log_directory: str | Path,
        *,
        max_bytes: int = 512_000,
        backup_count: int = 3,
    ) -> None:
        self.log_directory = Path(log_directory)
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_directory / "ai_master_pro_crash.log"
        self.logger = logging.getLogger(f"ai_master_pro.crash.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        handler = RotatingFileHandler(
            self.log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%SZ",
            )
        )
        handler.formatter.converter = __import__("time").gmtime
        self.logger.addHandler(handler)

        self._installed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._previous_sys_hook = None
        self._previous_thread_hook = None
        self._previous_loop_handler = None

    def capture_exception(self, error: BaseException, context: str) -> None:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            return
        formatted = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        self.logger.error(
            "%s\n%s",
            redact_secrets(context),
            redact_secrets(formatted).rstrip(),
        )

    def capture_message(self, message: object, *, level: int = logging.WARNING) -> None:
        self.logger.log(level, "%s", redact_secrets(message))

    def capture_flet_event(self, event: Any) -> None:
        detail = getattr(event, "data", None) or getattr(event, "error", None) or event
        self.capture_exception(
            RuntimeError(redact_secrets(detail)),
            "Unhandled Flet page event",
        )

    def install(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Install process-level hooks once for this app session."""
        global _ACTIVE_PROTECTOR
        if self._installed:
            return

        self._previous_sys_hook = sys.excepthook
        self._previous_thread_hook = getattr(threading, "excepthook", None)

        def sys_hook(
            exception_type: type[BaseException],
            exception: BaseException,
            exception_traceback: TracebackType | None,
        ) -> None:
            if issubclass(exception_type, KeyboardInterrupt):
                if self._previous_sys_hook is not None:
                    self._previous_sys_hook(
                        exception_type, exception, exception_traceback
                    )
                return
            if exception.__traceback__ is None and exception_traceback is not None:
                exception = exception.with_traceback(exception_traceback)
            self.capture_exception(exception, "Uncaught Python exception")

        def thread_hook(arguments: Any) -> None:
            thread_name = getattr(getattr(arguments, "thread", None), "name", "unknown")
            exception = getattr(arguments, "exc_value", RuntimeError("Unknown thread error"))
            self.capture_exception(exception, f"Uncaught thread exception ({thread_name})")

        sys.excepthook = sys_hook
        if hasattr(threading, "excepthook"):
            threading.excepthook = thread_hook

        self._loop = loop
        if loop is not None:
            self._previous_loop_handler = loop.get_exception_handler()

            def loop_handler(
                _loop: asyncio.AbstractEventLoop,
                context: dict[str, Any],
            ) -> None:
                error = context.get("exception")
                message = context.get("message", "Unhandled asynchronous task error")
                if isinstance(error, BaseException):
                    self.capture_exception(error, message)
                else:
                    self.capture_exception(RuntimeError(str(message)), "Asyncio error")

            loop.set_exception_handler(loop_handler)

        _ACTIVE_PROTECTOR = self
        self._installed = True
        self.capture_message("Crash protection initialized.", level=logging.INFO)

    def restore(self) -> None:
        """Restore hooks; mainly useful for tests and controlled shutdown."""
        global _ACTIVE_PROTECTOR
        if not self._installed:
            return
        if self._previous_sys_hook is not None:
            sys.excepthook = self._previous_sys_hook
        if self._previous_thread_hook is not None and hasattr(threading, "excepthook"):
            threading.excepthook = self._previous_thread_hook
        if self._loop is not None and not self._loop.is_closed():
            self._loop.set_exception_handler(self._previous_loop_handler)
        if _ACTIVE_PROTECTOR is self:
            _ACTIVE_PROTECTOR = None
        for handler in tuple(self.logger.handlers):
            handler.flush()
            handler.close()
            self.logger.removeHandler(handler)
        self._installed = False


def report_exception(error: BaseException, context: str) -> None:
    """Report a handled failure when crash protection is active."""
    if _ACTIVE_PROTECTOR is not None:
        _ACTIVE_PROTECTOR.capture_exception(error, context)
