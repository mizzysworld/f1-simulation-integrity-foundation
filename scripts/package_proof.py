"""Inspect built wheel and source archives before publication."""

from __future__ import annotations

import json
import stat
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BLOCKED_SUFFIXES = {".docx", ".key", ".p12", ".pdf", ".pem", ".pyc", ".zip"}
BLOCKED_NAMES = {"credentials.json", "token.json", ".ds_store", ".env"}


def validate_name(name: str) -> None:
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or (len(name) >= 2 and name[0].isalpha() and name[1] == ":")
    ):
        raise ValueError(f"unsafe archive member: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "" in path.parts:
        raise ValueError(f"unsafe archive member: {name}")
    member_name = path.name.lower()
    if (
        member_name in BLOCKED_NAMES
        or member_name.startswith(".env.")
        or path.suffix.lower() in BLOCKED_SUFFIXES
        or "__pycache__" in path.parts
    ):
        raise ValueError(f"blocked archive member: {name}")


def validate_wheel_member(member: zipfile.ZipInfo) -> None:
    validate_name(member.filename)
    mode = (member.external_attr >> 16) & 0xFFFF
    member_type = stat.S_IFMT(mode)
    if member_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ValueError(f"unsafe wheel member type: {member.filename}")


def main() -> int:
    wheels = sorted(DIST.glob("*.whl"))
    sdists = sorted(DIST.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("expected exactly one wheel and one source distribution")
    with zipfile.ZipFile(wheels[0]) as archive:
        wheel_members = archive.infolist()
        for member in wheel_members:
            validate_wheel_member(member)
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
                "wheelMembers": len(wheel_members),
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
