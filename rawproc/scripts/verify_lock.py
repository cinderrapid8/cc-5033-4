#!/usr/bin/env python3
"""Verify the raw-decoder build lock.

The decoder is an in-tree package rather than an index-installed wheel, so the
"lock" is a path + version + sha256 of the package sources.  This script:

  1. hashes every tracked ``.py`` file under the locked decoder directory;
  2. compares it with the sha256 recorded in ``requirements-lock.txt``;
  3. checks the same version appears in the decoder, the lock file and
     ``pyproject.toml``.

Run with the isolated interpreter, from the project root::

    python3 -I scripts/verify_lock.py
"""

from __future__ import annotations

import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECODER_DIR = os.path.join(ROOT, "rawproc", "rawdecode")
LOCK = os.path.join(ROOT, "requirements-lock.txt")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")


def hash_package() -> tuple[str, list[str]]:
    files = []
    digest = hashlib.sha256()
    for dirpath, _dirs, names in os.walk(DECODER_DIR):
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, ROOT)
            files.append(rel)
            with open(full, "rb") as fh:
                digest.update(rel.encode("utf-8"))
                digest.update(b"\0")
                digest.update(fh.read())
                digest.update(b"\0")
    return digest.hexdigest(), files


def locked_hash() -> str:
    with open(LOCK, "r", encoding="utf-8") as fh:
        for line in fh:
            m = re.search(r"#\s*sha256=([0-9a-f]{64})", line)
            if m:
                return m.group(1)
    raise SystemExit("FAIL: no sha256 entry found in requirements-lock.txt")


def decoder_version() -> str:
    # The canonical assignment lives in decoder.py; __init__.py re-exports it.
    src = open(os.path.join(DECODER_DIR, "decoder.py"),
               "r", encoding="utf-8").read()
    m = re.search(r'DECODER_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', src)
    if not m:
        raise SystemExit("FAIL: DECODER_VERSION not found in rawdecode")
    return m.group(1)


def main() -> int:
    actual_hash, files = hash_package()
    expected_hash = locked_hash()
    version = decoder_version()

    pyproject = open(PYPROJECT, "r", encoding="utf-8").read()
    lock_text = open(LOCK, "r", encoding="utf-8").read()

    failures = []
    if actual_hash != expected_hash:
        failures.append(
            f"decoder source hash mismatch:\n  locked  {expected_hash}\n"
            f"  actual  {actual_hash}\n  update requirements-lock.txt after "
            "reviewing the decoder change")
    if f"rawdecode == {version} " not in lock_text:
        failures.append(
            f"requirements-lock.txt does not pin rawdecode == {version}")
    if f'version = "{version}"' not in pyproject:
        failures.append(
            f"pyproject.toml [tool.rawproc.raw-decoder] version != {version}")

    print(f"decoder package : {os.path.relpath(DECODER_DIR, ROOT)} "
          f"({len(files)} modules)")
    print(f"decoder version : {version}")
    print(f"source sha256   : {actual_hash}")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("LOCK OK: hash matches and version is consistent across the "
          "decoder, lock file and pyproject.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
