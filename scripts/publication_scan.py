"""Fail-closed publication scan for the public reference tree."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED_PARTS = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
}
BLOCKED_SUFFIXES = {".docx", ".key", ".p12", ".pdf", ".pem", ".pyc", ".zip"}
BLOCKED_NAMES = {"credentials.json", "token.json", ".ds_store", ".env"}
TEXT_PATTERNS = {
    "absolute macOS user path": re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    "absolute Linux home path": re.compile(r"/home/[A-Za-z0-9._-]+/"),
    "absolute Windows user path": re.compile(r"[A-Za-z]:\\Users\\"),
    "GitHub token": re.compile(r"\b(?:gh[opsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
BLOCKED_IMPORT_ROOTS = {
    "ftplib",
    "httpx",
    "requests",
    "socket",
    "subprocess",
}
BLOCKED_CALLS = {"eval", "exec"}
BLOCKED_ATTRIBUTES = {
    ("os", "popen"),
    ("os", "system"),
    ("subprocess", "Popen"),
    ("subprocess", "call"),
    ("subprocess", "run"),
}


def ignored_generated_path(relative: Path) -> bool:
    return any(
        part in IGNORED_PARTS or part.lower().endswith(".egg-info")
        for part in relative.parts
    )


def validate_tracked_path(path: Path) -> None:
    relative = path.relative_to(ROOT)
    if "__pycache__" in relative.parts or ignored_generated_path(relative):
        raise ValueError(f"tracked generated path is not publishable: {relative}")


def scanned_files() -> list[Path]:
    tracked: set[Path] | None = None
    if (ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        tracked = {
            Path(item.decode()) for item in result.stdout.split(b"\0") if item
        }
        for relative in tracked:
            validate_tracked_path(ROOT / relative)
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if "__pycache__" in relative.parts and tracked is not None and relative not in tracked:
            continue
        if ignored_generated_path(relative):
            continue
        if path.is_symlink():
            raise ValueError(f"symlink is not publishable: {relative}")
        if path.is_file():
            files.append(path)
    return files


def blocked_artifact(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in BLOCKED_NAMES
        or name.startswith(".env.")
        or path.suffix.lower() in BLOCKED_SUFFIXES
    )


def inspect_runtime(path: Path, text: str) -> None:
    tree = ast.parse(text, filename=str(path.relative_to(ROOT)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {alias.name.split(".")[0] for alias in node.names}
            blocked = names & BLOCKED_IMPORT_ROOTS
            if blocked:
                raise ValueError(
                    f"blocked runtime import {sorted(blocked)} in {path.relative_to(ROOT)}"
                )
        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BLOCKED_IMPORT_ROOTS or (node.module or "").startswith("urllib.request"):
                raise ValueError(
                    f"blocked runtime import {node.module} in {path.relative_to(ROOT)}"
                )
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                raise ValueError(f"blocked dynamic call {node.func.id} in {path.relative_to(ROOT)}")
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and (node.func.value.id, node.func.attr) in BLOCKED_ATTRIBUTES
            ):
                raise ValueError(
                    f"blocked process call {node.func.value.id}.{node.func.attr} "
                    f"in {path.relative_to(ROOT)}"
                )


def main() -> int:
    files = scanned_files()
    for path in files:
        relative = path.relative_to(ROOT)
        if blocked_artifact(path):
            raise ValueError(f"blocked publication artifact: {relative}")
        encoded = path.read_bytes()
        if b"\x00" in encoded:
            raise ValueError(f"binary/NUL content is not publishable: {relative}")
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"non-UTF-8 artifact is not publishable: {relative}") from error
        for label, pattern in TEXT_PATTERNS.items():
            if pattern.search(text):
                raise ValueError(f"{label} found in {relative}")
        if path.suffix == ".json":
            json.loads(text)
        elif path.suffix == ".toml":
            tomllib.loads(text)
        if relative.parts[0] == "src" and path.suffix == ".py":
            inspect_runtime(path, text)
    result = {
        "status": "PASS",
        "filesScanned": len(files),
        "runtimePythonFiles": sum(
            path.suffix == ".py" and path.relative_to(ROOT).parts[0] == "src" for path in files
        ),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from error
