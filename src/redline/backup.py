"""Consistent SQLite snapshots plus immutable materials; no secrets in archives."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile

from .runtime import FileLock, load_dotenv


def create_backup(data: Path, destination: Path, keep: int = 7) -> Path:
    if keep < 1:
        raise ValueError("Backup retention must be at least one archive.")
    destination.mkdir(parents=True, exist_ok=True)
    with FileLock(str(destination / ".backup.lock"), timeout=60):
        source = data / "bot.db"
        if not source.exists():
            raise FileNotFoundError("No database to back up.")
        name = f"redline-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}.zip"
        output = destination / name
        pending = output.with_suffix(".partial")
        try:
            with tempfile.TemporaryDirectory(dir=destination) as temp:
                snapshot = Path(temp) / "bot.db"
                with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(snapshot)) as dst:
                    src.backup(dst)
                    if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("Database integrity check failed.")
                    if dst.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_files'").fetchone():
                        rows = dst.execute("SELECT DISTINCT file_name FROM listings WHERE file_name IS NOT NULL UNION SELECT DISTINCT stored_name FROM product_files").fetchall()
                    else:
                        rows = dst.execute("SELECT DISTINCT file_name FROM listings WHERE file_name IS NOT NULL").fetchall()
                manifest: dict[str, str] = {}
                paths = [(snapshot, "bot.db")] + [(data / "materials" / r[0], "materials/" + r[0]) for r in rows]
                with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path, member in paths:
                        with path.open("rb") as stream:
                            digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        manifest[member] = digest
                        archive.write(path, member)
                    archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            pending.replace(output)
            for old in sorted(destination.glob("redline-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[keep:]:
                old.unlink()
            return output
        finally:
            pending.unlink(missing_ok=True)


def restore(archive: Path, target: Path) -> None:
    # Restore only into a new, empty directory. Never overwrite a running database.
    if target.exists() and any(target.iterdir()):
        raise ValueError("Restore target must be empty. Stop the worker and use a NEW directory.")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        if "bot.db" not in manifest:
            raise ValueError("Missing database in backup.")
        if set(z.namelist()) != set(manifest) | {"manifest.json"}:
            raise ValueError("Archive has unexpected entries.")
        for name, digest in manifest.items():
            path = target / name
            if target.resolve() not in path.resolve().parents or "\\" in name:
                raise ValueError("Unsafe archive path.")
            if name != "bot.db" and not (name.startswith("materials/") and len(Path(name).parts) == 2):
                raise ValueError("Unexpected backup path.")
            with z.open(name) as stream:
                checksum = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(chunk)
                if checksum.hexdigest() != digest:
                    raise ValueError("Backup checksum mismatch.")
        for name in manifest:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    with closing(sqlite3.connect(target / "bot.db")) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Restored database failed integrity check.")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create")
    rest = sub.add_parser("restore")
    rest.add_argument("archive", type=Path)
    rest.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "restore":
        restore(args.archive, args.target)
        print(f"Verified restore complete: {args.target}")
    else:
        print(create_backup(Path(os.getenv("DATA_DIR", "./data")),
                            Path(os.getenv("BACKUP_DIR", "./backups")),
                            int(os.getenv("BACKUP_KEEP", "7"))))


if __name__ == "__main__":
    main()

