"""Tails one or more log files, yielding new lines as they are written."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Generator, List

logger = logging.getLogger(__name__)

_WAIT_SECS = 0.5  # poll interval when no new data
_MAX_LINE_BYTES = 16_384  # truncate absurdly long lines


class LogTailer:
    """Tails a log file from its current end, yielding new lines.

    Handles log rotation by detecting when the file shrinks (inode change or
    size decrease) and re-opening from the new file.
    """

    def __init__(self, path: str, tail_lines: int = 0) -> None:
        self.path = path
        self.tail_lines = tail_lines  # 0 = start from end; >0 = include last N lines
        self._file = None
        self._inode: int = -1
        self._pos: int = 0

    def _open(self) -> bool:
        """Open the file and seek to the correct position. Returns True on success."""
        try:
            f = open(self.path, "r", encoding="utf-8", errors="replace")
            stat = os.fstat(f.fileno())
            self._inode = stat.st_ino
            if self.tail_lines > 0 and self._pos == 0:
                # Seek to last N lines
                f.seek(0, 2)
                size = f.tell()
                block = min(size, self.tail_lines * 200)
                f.seek(max(0, size - block))
                lines = f.readlines()
                # Re-seek to where we want to start
                f.seek(0, 2)
                for line in lines[-self.tail_lines :]:
                    yield line.rstrip("\n")
            else:
                f.seek(0, 2)  # start from end
            self._pos = f.tell()
            if self._file:
                self._file.close()
            self._file = f
            logger.debug(
                "LogTailer opened: %s (inode=%d pos=%d)", self.path, self._inode, self._pos
            )
            return True
        except (OSError, IOError) as exc:
            logger.warning("LogTailer: cannot open %s: %s", self.path, exc)
            return False

    def _check_rotation(self) -> bool:
        """Return True if the file has been rotated or recreated."""
        try:
            stat = os.stat(self.path)
            if stat.st_ino != self._inode:
                return True  # rotated — new file
            if self._file and stat.st_size < self._pos:
                return True  # truncated
            return False
        except OSError:
            return True

    def lines(self) -> Generator[str, None, None]:
        """Yield new lines continuously. Blocks when no new data."""
        if not Path(self.path).exists():
            logger.info("LogTailer: waiting for %s to appear…", self.path)

        while not Path(self.path).exists():
            time.sleep(2)

        yield from self._open()

        while True:
            if self._check_rotation():
                logger.info("LogTailer: rotation detected for %s, reopening", self.path)
                self._pos = 0
                yield from self._open()
                continue

            if self._file is None:
                time.sleep(_WAIT_SECS)
                yield from self._open()
                continue

            line = self._file.readline()
            if not line:
                time.sleep(_WAIT_SECS)
                continue

            self._pos = self._file.tell()
            line = line.rstrip("\n")
            if len(line) > _MAX_LINE_BYTES:
                line = line[:_MAX_LINE_BYTES] + "…[truncated]"
            yield line

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None


class MultiLogTailer:
    """Tails multiple log files, interleaving lines with a source tag."""

    def __init__(self, paths: List[str], tail_lines: int = 0) -> None:
        self._tailers = {p: LogTailer(p, tail_lines) for p in paths}

    def lines(self) -> Generator[tuple[str, str], None, None]:
        """Yield (path, line) tuples from all tailed files, round-robin."""
        import threading

        queue: list = []
        lock = threading.Lock()

        def _tail(path: str, tailer: LogTailer) -> None:
            for line in tailer.lines():
                with lock:
                    queue.append((path, line))

        threads = []
        for path, tailer in self._tailers.items():
            t = threading.Thread(target=_tail, args=(path, tailer), daemon=True)
            t.start()
            threads.append(t)

        while True:
            with lock:
                if queue:
                    yield queue.pop(0)
                    continue
            time.sleep(0.1)

    def close(self) -> None:
        for t in self._tailers.values():
            t.close()
