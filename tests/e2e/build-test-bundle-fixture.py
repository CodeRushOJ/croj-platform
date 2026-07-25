#!/usr/bin/env python3

import pathlib
import stat
import sys
import zipfile


FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
REGULAR_FILE_MODE = (stat.S_IFREG | 0o600) << 16


def fail(message):
    raise SystemExit(f"build-test-bundle-fixture: {message}")


def validate_entry(name):
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or "\0" in name
        or "//" in name
    ):
        fail("entry path is unsafe")
    parts = pathlib.PurePosixPath(name).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        fail("entry path is unsafe")


def main(arguments):
    if len(arguments) < 4:
        fail("usage: ROOT OUTPUT ENTRY [ENTRY ...]")

    root = pathlib.Path(arguments[1]).resolve(strict=True)
    output = pathlib.Path(arguments[2])
    entries = arguments[3:]
    if not root.is_dir() or len(entries) != len(set(entries)):
        fail("root must be a directory and entries must be unique")

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=0,
        strict_timestamps=True,
    ) as archive:
        for name in entries:
            validate_entry(name)
            candidate = root / pathlib.PurePosixPath(name)
            if candidate.is_symlink():
                fail("entry must be a regular file below root")
            source = candidate.resolve(strict=True)
            if root not in source.parents or not source.is_file():
                fail("entry must be a regular file below root")
            info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
            info.create_system = 3
            info.external_attr = REGULAR_FILE_MODE
            info.compress_type = zipfile.ZIP_DEFLATED
            info.flag_bits |= 0x800
            archive.writestr(
                info,
                source.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=0,
            )


if __name__ == "__main__":
    main(sys.argv)
