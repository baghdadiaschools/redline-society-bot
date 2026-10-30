"""Compile-check and build a source-only Python zipapp, excluding all user data."""
import compileall
from pathlib import Path
import shutil
import tempfile
import zipapp

root = Path(__file__).resolve().parents[1]
if not compileall.compile_dir(root / "src", quiet=1):
    raise SystemExit("Compilation failed")
(root / "dist").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as temp:
    staging = Path(temp)
    shutil.copytree(root / "src" / "redline", staging / "redline",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    zipapp.create_archive(staging, root / "dist" / "redline.pyz",
                         main="redline.__main__:main", compressed=True)
print("Built dist/redline.pyz (runtime dependencies are installed separately)")

