"""Small cross-platform runtime helpers, using only the standard library."""
from contextlib import AbstractContextManager
import os
from pathlib import Path
import time
from typing import IO, Any


def load_dotenv() -> None:
    """Read simple KEY=value pairs; never override host-provided environment values."""
    path = Path(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip().replace("_", "").isalnum():
            raise ValueError("Invalid .env line; use KEY=value.")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


class FileLock(AbstractContextManager["FileLock"]):
    def __init__(self, path: str, timeout: int = 0):
        self.path = path
        self.timeout = timeout
        self.handle: IO[bytes] | None = None

    def __enter__(self) -> "FileLock":
        self.handle = open(self.path, "a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        start = time.monotonic()
        while True:
            try:
                self.handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() - start >= self.timeout:
                    self.handle.close()
                    self.handle = None
                    raise TimeoutError("Data directory is locked by another process.") from None
                time.sleep(0.1)

    def __exit__(self, *args: Any) -> None:
        if self.handle:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None

