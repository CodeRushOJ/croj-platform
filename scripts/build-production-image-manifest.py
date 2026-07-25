#!/usr/bin/env python3
"""Validate component release manifests and emit digest-only production values."""

import argparse
import json
import pathlib
import re
import sys


COMPONENTS = ("frontend", "backend", "judging-server", "sandbox", "docs")
CHART_KEYS = {
    "frontend": "frontend",
    "backend": "backend",
    "judging-server": "judgingServer",
    "sandbox": "sandbox",
    "docs": "docs",
}
REPOSITORIES = {
    "frontend": "ghcr.io/coderushoj/croj-frontend",
    "backend": "ghcr.io/coderushoj/croj-backend",
    "judging-server": "ghcr.io/coderushoj/croj-judging-server",
    "sandbox": "ghcr.io/coderushoj/croj-sandbox",
    "docs": "ghcr.io/coderushoj/coderushoj-docs",
}
MANIFEST_FIELDS = {"repository", "tag", "revision", "digest", "platforms"}
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PLATFORMS = ["linux/amd64", "linux/arm64"]


class ManifestError(Exception):
    """A release input is not safe to publish."""


def read_json(path, description):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as error:
        raise ManifestError(f"{description} does not exist: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read {description} {path}: {error}") from error


def expected_release_inputs(source_lock, platform_revision, platform_version):
    sources = source_lock.get("sources") if isinstance(source_lock, dict) else None
    if not isinstance(sources, dict):
        raise ManifestError("source lock must contain a sources object")
    revisions = {}
    tags = {}
    for component in COMPONENTS[:-1]:
        source = sources.get(component)
        revision = source.get("commit") if isinstance(source, dict) else None
        tag = source.get("releaseTag") if isinstance(source, dict) else None
        if not isinstance(revision, str) or not REVISION.fullmatch(revision):
            raise ManifestError(f"source lock has no valid commit for {component}")
        if not isinstance(tag, str) or not re.fullmatch(
            r"^v[0-9]+\.[0-9]+\.[0-9]+$", tag
        ):
            raise ManifestError(f"source lock has no valid releaseTag for {component}")
        revisions[component] = revision
        tags[component] = tag
    if not REVISION.fullmatch(platform_revision):
        raise ManifestError("platform revision must be a lowercase 40-character Git object ID")
    revisions["docs"] = platform_revision
    tags["docs"] = f"v{platform_version}"
    return revisions, tags


def parse_manifest_arguments(values):
    manifests = {}
    for value in values:
        component, separator, raw_path = value.partition("=")
        if not separator or component not in COMPONENTS or not raw_path:
            raise ManifestError(f"invalid --manifest value: {value}")
        if component in manifests:
            raise ManifestError(f"duplicate manifest for {component}")
        manifests[component] = pathlib.Path(raw_path)
    if set(manifests) != set(COMPONENTS):
        raise ManifestError(
            f"manifest set mismatch: expected {list(COMPONENTS)}, got {sorted(manifests)}"
        )
    return manifests


def validate_manifest(component, path, expected_tag, revision):
    payload = read_json(path, f"{component} image manifest")
    if not isinstance(payload, dict):
        raise ManifestError(f"{component}: manifest must be a JSON object")
    if set(payload) != MANIFEST_FIELDS:
        raise ManifestError(
            f"{component}: manifest fields must exactly equal {sorted(MANIFEST_FIELDS)}"
        )
    if payload["repository"] != REPOSITORIES[component]:
        raise ManifestError(f"{component}: unexpected repository")
    if payload["tag"] != expected_tag:
        raise ManifestError(f"{component}: tag must equal {expected_tag}")
    if payload["revision"] != revision:
        raise ManifestError(f"{component}: revision does not match the immutable source lock")
    if not isinstance(payload["digest"], str) or not DIGEST.fullmatch(payload["digest"]):
        raise ManifestError(f"{component}: digest must be a lowercase sha256 manifest digest")
    if payload["platforms"] != PLATFORMS:
        raise ManifestError(
            f"{component}: platforms must exactly equal {PLATFORMS}"
        )
    return payload


def write_outputs(output_directory, version, images):
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "production-images.json"
    json_path.write_text(
        json.dumps(
            {"schemaVersion": 1, "version": version, "images": images},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    yaml_lines = ["images:"]
    for component in COMPONENTS:
        yaml_lines.extend(
            (
                f"  {CHART_KEYS[component]}:",
                '    tag: ""',
                f'    digest: "{images[component]["digest"]}"',
            )
        )
    (output_directory / "production-images.yaml").write_text(
        "\n".join(yaml_lines) + "\n"
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-lock", required=True, type=pathlib.Path)
    parser.add_argument("--platform-revision", required=True)
    parser.add_argument("--manifest", action="append", default=[])
    parser.add_argument("--output-directory", required=True, type=pathlib.Path)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if not VERSION.fullmatch(args.version):
            raise ManifestError("version must be exact numeric SemVer")
        manifests = parse_manifest_arguments(args.manifest)
        revisions, tags = expected_release_inputs(
            read_json(args.source_lock, "source lock"),
            args.platform_revision,
            args.version,
        )
        images = {
            component: validate_manifest(
                component,
                manifests[component],
                tags[component],
                revisions[component],
            )
            for component in COMPONENTS
        }
        write_outputs(args.output_directory, args.version, images)
    except ManifestError as error:
        print(f"release image manifest validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
