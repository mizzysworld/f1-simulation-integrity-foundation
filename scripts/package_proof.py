"""Inspect built wheel and source archives before publication."""

from __future__ import annotations

import json
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BLOCKED_SUFFIXES = {".docx", ".env", ".key", ".p12", ".pdf", ".pem", ".pyc", ".zip"}


def validate_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "" in path.parts:
        raise ValueError(f"unsafe archive member: {name}")
    if path.suffix.lower() in BLOCKED_SUFFIXES or "__pycache__" in path.parts:
        raise ValueError(f"blocked archive member: {name}")


def main() -> int:
    wheels = sorted(DIST.glob("*.whl"))
    sdists = sorted(DIST.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("expected exactly one wheel and one source distribution")
    with zipfile.ZipFile(wheels[0]) as archive:
        wheel_names = archive.namelist()
        for name in wheel_names:
            validate_name(name)
    with tarfile.open(sdists[0], "r:gz") as archive:
        sdist_members = archive.getmembers()
        for member in sdist_members:
            validate_name(member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise ValueError(f"unsafe source archive member type: {member.name}")
    print(
        json.dumps(
            {
                "status": "PASS",
                "wheel": wheels[0].name,
                "wheelMembers": len(wheel_names),
                "sdist": sdists[0].name,
                "sdistMembers": len(sdist_members),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from error
