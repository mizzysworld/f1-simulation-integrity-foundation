"""Adversarial self-test for package-member publication policy."""

from __future__ import annotations

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
    print("package proof self-test: PASS (6/6)")


if __name__ == "__main__":
    main()
