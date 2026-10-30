"""Container liveness probe: gateway readiness must refresh within 3 minutes."""
import os
from pathlib import Path
import sys
import time


def main() -> None:
    try:
        stamp = float((Path(os.getenv("DATA_DIR", "./data")) / "heartbeat").read_text())
        sys.exit(0 if time.time() - stamp < 180 else 1)
    except (OSError, ValueError):
        sys.exit(1)


if __name__ == "__main__":
    main()
