from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO


class _TeeStream:
    """Mirror writes to the original console stream and a log file."""

    def __init__(self, console_stream: TextIO, file_stream: TextIO):
        self._console = console_stream
        self._file = file_stream
        self.encoding = getattr(console_stream, "encoding", "utf-8")

    def write(self, data: str) -> int:
        if not data:
            return 0
        self._console.write(data)
        self._file.write(data)
        return len(data)

    def flush(self) -> None:
        self._console.flush()
        self._file.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._console, "isatty", lambda: False)())


_initialized = False
_current_log_path: str | None = None


def setup_runtime_file_logging() -> str | None:
    """
    Tee all stdout/stderr output into a text log file.

    Env controls:
    - VERBOSE_LOG_TO_FILE: "1"/"0" (default: "1")
    - VERBOSE_LOG_FILE: explicit file path (optional)
    - VERBOSE_LOG_DIR: directory for generated log files (default: "logs")
    - VERBOSE_LOG_PREFIX: filename prefix (default: "trading_session")
    """
    global _initialized, _current_log_path

    if _initialized:
        return _current_log_path

    enabled = os.getenv("VERBOSE_LOG_TO_FILE", "1").strip().lower() not in {"0", "false", "no", "off"}
    if not enabled:
        _initialized = True
        return None

    explicit_file = os.getenv("VERBOSE_LOG_FILE", "").strip()
    if explicit_file:
        log_path = Path(explicit_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        log_dir = Path(os.getenv("VERBOSE_LOG_DIR", "logs"))
        prefix = os.getenv("VERBOSE_LOG_PREFIX", "trading_session").strip() or "trading_session"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path = log_dir / f"{prefix}_{stamp}.txt"

    file_stream = open(log_path, mode="a", encoding="utf-8", buffering=1)
    file_stream.write(f"\n=== Session started {datetime.now().isoformat(timespec='seconds')} ===\n")

    sys.stdout = _TeeStream(sys.stdout, file_stream)
    sys.stderr = _TeeStream(sys.stderr, file_stream)

    _current_log_path = str(log_path)
    _initialized = True
    print(f"[LOG] Runtime output is being saved to: {_current_log_path}")
    return _current_log_path
