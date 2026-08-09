"""Adversarial self-test for package-member publication policy."""

from __future__ import annotations

import stat
import tarfile
import zipfile

import package_proof


def expect_failure(name: str) -> None:
    try:
        package_proof.validate_name(name)
    except ValueError:
        return
    raise AssertionError(f"package proof failed open for {name}")


def main() -> None:
    package_proof.validate_name("safe/package/module.py")
    expect_failure(".env")
    expect_failure("config/.env.local")
    expect_failure("src/package/module.pyc")
    expect_failure("src/package/__pycache__/module.cpython-314.pyc")
    expect_failure("../escape.txt")
    expect_failure(r"..\escape.txt")
    expect_failure(r"C:\absolute.txt")
    expect_failure("C:/absolute.txt")
    symlink = zipfile.ZipInfo("safe/link")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    try:
        package_proof.validate_wheel_member(symlink)
    except ValueError:
        pass
    else:
        raise AssertionError("package proof failed open for wheel symlink member")
    unknown = tarfile.TarInfo("safe/unknown")
    unknown.type = b"Z"
    try:
        package_proof.validate_sdist_member(unknown)
    except ValueError:
        pass
    else:
        raise AssertionError("package proof failed open for unknown sdist member type")
    print("package proof self-test: PASS (11/11)")


if __name__ == "__main__":
    main()
