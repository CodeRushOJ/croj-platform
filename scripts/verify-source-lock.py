#!/usr/bin/env python3
"""Validate and normalize the immutable CodeRushOJ source lock."""

import argparse
import json
import pathlib
import re
import sys


COMPONENTS = ("frontend", "backend", "judging-server", "sandbox")
REPOSITORIES = {
    "frontend": "croj-frontend",
    "backend": "croj-backend",
    "judging-server": "croj-judging-server",
    "sandbox": "croj-sandbox",
}
IMAGES = {
    "frontend": "ghcr.io/coderushoj/croj-frontend:dev",
    "backend": "ghcr.io/coderushoj/croj-backend:dev",
    "judging-server": "ghcr.io/coderushoj/croj-judging-server:dev",
    "sandbox": "ghcr.io/coderushoj/croj-sandbox:dev",
}
RELEASE_MANIFEST_ASSETS = {
    "frontend": "image-artifact.json",
    "backend": "backend-image.json",
    "judging-server": "judging-server-image.json",
    "sandbox": "sandbox-image.json",
}
SOURCE_FIELDS = {
    "repository",
    "commit",
    "releaseTag",
    "context",
    "dockerfile",
    "image",
    "releaseManifestAsset",
    "releaseManifestSha256",
}
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RELEASE_TAG_PATTERN = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class LockValidationError(Exception):
    """Raised when a source lock violates its contract."""


def contains_ascii_control(value):
    return isinstance(value, str) and any(
        ord(character) < 32 or ord(character) == 127 for character in value
    )


def is_safe_relative_path(value):
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or contains_ascii_control(value)
    ):
        return False
    path = pathlib.PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def validate_lock(lock_path):
    try:
        payload = json.loads(lock_path.read_text())
    except FileNotFoundError as error:
        raise LockValidationError(f"lock file does not exist: {lock_path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise LockValidationError(f"cannot read source lock {lock_path}: {error}") from error

    errors = []
    if not isinstance(payload, dict):
        raise LockValidationError("source lock must be a JSON object")

    unknown_top_level = set(payload) - {"schemaVersion", "sources"}
    if unknown_top_level:
        errors.append(f"unknown top-level field(s): {', '.join(sorted(unknown_top_level))}")
    if payload.get("schemaVersion") != 3:
        errors.append("schemaVersion must equal 3")

    sources = payload.get("sources")
    if not isinstance(sources, dict):
        errors.append("sources must be an object")
        sources = {}

    actual_components = set(sources)
    expected_components = set(COMPONENTS)
    if actual_components != expected_components:
        missing = sorted(expected_components - actual_components)
        extra = sorted(actual_components - expected_components)
        errors.append(f"component set mismatch (missing={missing}, extra={extra})")

    normalized = []
    images = []
    for component in COMPONENTS:
        source = sources.get(component)
        if not isinstance(source, dict):
            if component in sources:
                errors.append(f"{component}: source must be an object")
            continue

        unknown_fields = set(source) - SOURCE_FIELDS
        missing_fields = SOURCE_FIELDS - set(source)
        if unknown_fields:
            errors.append(f"{component}: unknown field(s): {', '.join(sorted(unknown_fields))}")
        if missing_fields:
            errors.append(f"{component}: missing field(s): {', '.join(sorted(missing_fields))}")
        for field in SOURCE_FIELDS:
            if contains_ascii_control(source.get(field)):
                errors.append(
                    f"{component}: {field} must not contain ASCII control characters"
                )

        repository = source.get("repository")
        expected_repository = f"https://github.com/CodeRushOJ/{REPOSITORIES[component]}.git"
        if repository != expected_repository:
            errors.append(
                f"{component}: repository must be the CodeRushOJ GitHub repository "
                f"{expected_repository}"
            )

        commit = source.get("commit")
        if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
            errors.append(f"{component}: commit must be a lowercase 40-character Git object ID")

        release_tag = source.get("releaseTag")
        if not isinstance(release_tag, str) or not RELEASE_TAG_PATTERN.fullmatch(
            release_tag
        ):
            errors.append(f"{component}: releaseTag must be an exact v-prefixed SemVer tag")

        context = source.get("context")
        if not is_safe_relative_path(context):
            errors.append(
                f"{component}: context must be a safe relative path without ASCII control characters"
            )

        dockerfile = source.get("dockerfile")
        if not is_safe_relative_path(dockerfile):
            errors.append(
                f"{component}: dockerfile must be a safe relative path without ASCII control characters"
            )

        image = source.get("image")
        if image != IMAGES[component]:
            errors.append(f"{component}: image must be the exact development image {IMAGES[component]}")
        if isinstance(image, str):
            images.append(image)

        release_manifest_asset = source.get("releaseManifestAsset")
        if release_manifest_asset != RELEASE_MANIFEST_ASSETS[component]:
            errors.append(
                f"{component}: releaseManifestAsset must be the exact asset filename "
                f"{RELEASE_MANIFEST_ASSETS[component]}"
            )

        release_manifest_sha256 = source.get("releaseManifestSha256")
        if (
            not isinstance(release_manifest_sha256, str)
            or not SHA256_PATTERN.fullmatch(release_manifest_sha256)
        ):
            errors.append(
                f"{component}: releaseManifestSha256 must be a lowercase "
                "64-character SHA-256"
            )

        if not missing_fields:
            normalized.append((component, repository, commit, context, dockerfile, image))

    duplicates = sorted({image for image in images if images.count(image) > 1})
    if duplicates:
        errors.append(f"duplicate image value(s): {', '.join(duplicates)}")

    if errors:
        raise LockValidationError("\n".join(errors))
    return normalized


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "rows", "records"))
    parser.add_argument(
        "--lock",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1] / "config/source-lock.json",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        rows = validate_lock(args.lock)
    except LockValidationError as error:
        print(f"source lock validation failed:\n{error}", file=sys.stderr)
        return 1

    if args.command == "validate":
        print(f"source lock is valid: {args.lock} ({len(rows)} sources)")
    elif args.command == "rows":
        for row in rows:
            print("\t".join(row))
    else:
        for row in rows:
            for field in row:
                sys.stdout.buffer.write(field.encode("utf-8") + b"\0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
