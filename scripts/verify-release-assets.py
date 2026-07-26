#!/usr/bin/env python3
"""Verify that an existing GitHub Release is the exact release for this checkout."""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tarfile


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
IMAGE_FIELDS = {"repository", "tag", "revision", "digest", "platforms"}
PLATFORMS = ["linux/amd64", "linux/arm64"]
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
CHECKSUM_PATTERN = re.compile(r"^([0-9a-f]{64})  \./([^/\r\n]+)$")


class VerificationError(Exception):
    """An existing release is not safe to resume or accept."""


def reject_duplicate_keys(pairs):
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def read_json(path, description):
    try:
        return json.loads(
            path.read_text(),
            object_pairs_hook=reject_duplicate_keys,
        )
    except FileNotFoundError as error:
        raise VerificationError(f"{description} does not exist: {path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise VerificationError(f"cannot read {description} {path}: {error}") from error


def read_version(path):
    try:
        raw_version = path.read_text()
    except (OSError, UnicodeError) as error:
        raise VerificationError(f"cannot read VERSION file {path}: {error}") from error
    version = raw_version.rstrip("\r\n")
    if raw_version not in {version, version + "\n", version + "\r\n"}:
        raise VerificationError("VERSION must contain one exact numeric SemVer")
    if not VERSION_PATTERN.fullmatch(version):
        raise VerificationError("VERSION must contain one exact numeric SemVer")
    return version


def sha256(path):
    checksum = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                checksum.update(chunk)
    except OSError as error:
        raise VerificationError(f"cannot hash release asset {path}: {error}") from error
    return checksum.hexdigest()


def expected_asset_names(version):
    return {
        f"coderushoj-{version}.tgz",
        f"coderushoj-infra-{version}.tgz",
        "SHA256SUMS",
        "release-notes.md",
        "docs-image.json",
        "production-images.json",
        "production-images.yaml",
        "production-render.yaml",
    }


def validate_release_metadata(release, tag, assets, expected_names):
    if not isinstance(release, dict):
        raise VerificationError("release API response must be a JSON object")
    if release.get("tag_name") != tag:
        raise VerificationError(f"release tag_name must equal {tag}")
    if release.get("name") != f"CodeRushOJ {tag}":
        raise VerificationError("release title does not match the exact release tag")
    if release.get("author", {}).get("login") != "github-actions[bot]":
        raise VerificationError("release author must be github-actions[bot]")
    if release.get("prerelease") is not False:
        raise VerificationError("release must not be a prerelease")
    draft = release.get("draft")
    immutable = release.get("immutable")
    if draft is True:
        if immutable is not False:
            raise VerificationError("a resumable draft must not claim to be immutable")
        state = "draft"
    elif draft is False:
        if immutable is not True:
            raise VerificationError("a published release must be immutable")
        state = "published"
    else:
        raise VerificationError("release draft state must be boolean")

    api_assets = release.get("assets")
    if not isinstance(api_assets, list):
        raise VerificationError("release assets must be an array")
    assets_by_name = {}
    for asset in api_assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise VerificationError("release asset metadata is malformed")
        name = asset["name"]
        if name in assets_by_name:
            raise VerificationError(f"duplicate release asset metadata: {name}")
        assets_by_name[name] = asset
    if set(assets_by_name) != expected_names:
        raise VerificationError(
            "release asset set mismatch: "
            f"expected {sorted(expected_names)}, got {sorted(assets_by_name)}"
        )
    for name, asset in assets_by_name.items():
        path = assets / name
        try:
            size = path.stat().st_size
        except OSError as error:
            raise VerificationError(f"cannot stat release asset {path}: {error}") from error
        if asset.get("state") != "uploaded":
            raise VerificationError(f"release asset {name} is not fully uploaded")
        if asset.get("size") != size:
            raise VerificationError(f"release asset {name} size does not match API metadata")
        api_digest = asset.get("digest")
        if api_digest != f"sha256:{sha256(path)}":
            raise VerificationError(f"release asset {name} digest does not match API metadata")
    return state


def validate_asset_directory(assets, expected_names):
    try:
        actual_paths = list(assets.iterdir())
    except OSError as error:
        raise VerificationError(f"cannot list release assets {assets}: {error}") from error
    if any(path.is_symlink() for path in actual_paths):
        raise VerificationError("release asset directory must not contain symlinks")
    actual_names = {path.name for path in actual_paths if path.is_file()}
    if actual_names != expected_names:
        raise VerificationError(
            "downloaded asset set mismatch: "
            f"expected {sorted(expected_names)}, got {sorted(actual_names)}"
        )


def validate_checksums(assets, expected_names):
    checksum_path = assets / "SHA256SUMS"
    try:
        lines = checksum_path.read_text().splitlines()
    except (OSError, UnicodeError) as error:
        raise VerificationError(f"cannot read SHA256SUMS: {error}") from error
    expected_checked_names = expected_names - {"SHA256SUMS"}
    checksums = {}
    for line in lines:
        match = CHECKSUM_PATTERN.fullmatch(line)
        if match is None:
            raise VerificationError("SHA256SUMS contains a malformed or unsafe entry")
        checksum, name = match.groups()
        if name in checksums:
            raise VerificationError(f"SHA256SUMS contains duplicate asset {name}")
        checksums[name] = checksum
    if set(checksums) != expected_checked_names:
        raise VerificationError("SHA256SUMS must cover every non-checksum asset exactly once")
    for name, expected_checksum in checksums.items():
        if sha256(assets / name) != expected_checksum:
            raise VerificationError(f"checksum mismatch for release asset {name}")


def chart_source_files(chart_directory):
    files = {}
    try:
        paths = sorted(chart_directory.rglob("*"))
    except OSError as error:
        raise VerificationError(f"cannot inspect chart {chart_directory}: {error}") from error
    for path in paths:
        if path.is_symlink():
            raise VerificationError(f"chart source must not contain symlinks: {path}")
        if path.is_file():
            relative = path.relative_to(chart_directory).as_posix()
            try:
                files[relative] = path.read_bytes()
            except OSError as error:
                raise VerificationError(f"cannot read chart source {path}: {error}") from error
    return files


def chart_archive_files(archive, chart_name):
    files = {}
    try:
        with tarfile.open(archive, "r:gz") as package:
            for member in package.getmembers():
                path = pathlib.PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise VerificationError(f"chart archive contains unsafe path {member.name}")
                if not path.parts or path.parts[0] != chart_name:
                    raise VerificationError(
                        f"chart archive member must be rooted at {chart_name}/"
                    )
                if member.isdir():
                    continue
                if not member.isfile():
                    raise VerificationError(
                        f"chart archive contains non-regular member {member.name}"
                    )
                relative = pathlib.PurePosixPath(*path.parts[1:]).as_posix()
                if not relative or relative in files:
                    raise VerificationError("chart archive contains duplicate or empty path")
                extracted = package.extractfile(member)
                if extracted is None:
                    raise VerificationError(f"cannot read chart archive member {member.name}")
                files[relative] = extracted.read()
    except (OSError, tarfile.TarError) as error:
        raise VerificationError(f"cannot read chart archive {archive}: {error}") from error
    return files


def chart_metadata(contents, label):
    try:
        text = contents.decode("utf-8")
    except UnicodeError as error:
        raise VerificationError(f"{label} Chart.yaml must be UTF-8") from error

    metadata = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1].isspace():
            raise VerificationError(
                f"{label} Chart.yaml contains unsupported nested metadata at line {line_number}"
            )
        key, separator, raw_value = line.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key):
            raise VerificationError(
                f"{label} Chart.yaml contains invalid metadata at line {line_number}"
            )
        if key in metadata:
            raise VerificationError(f"{label} Chart.yaml contains duplicate key {key}")

        value = raw_value.strip()
        if not value:
            raise VerificationError(f"{label} Chart.yaml key {key} has no scalar value")
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as error:
                raise VerificationError(
                    f"{label} Chart.yaml key {key} has an invalid quoted value"
                ) from error
            if not isinstance(value, str):
                raise VerificationError(
                    f"{label} Chart.yaml key {key} must be a scalar string"
                )
        elif value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                raise VerificationError(
                    f"{label} Chart.yaml key {key} has an invalid quoted value"
                )
            value = value[1:-1].replace("''", "'")
        metadata[key] = value
    return metadata


def validate_chart(assets, chart_directory, chart_name, version):
    archive = assets / f"{chart_name}-{version}.tgz"
    packaged_files = chart_archive_files(archive, chart_name)
    source_files = chart_source_files(chart_directory)
    packaged_chart_yaml = packaged_files.pop("Chart.yaml", None)
    source_chart_yaml = source_files.pop("Chart.yaml", None)
    if packaged_chart_yaml is None or source_chart_yaml is None:
        raise VerificationError(f"{chart_name} Chart.yaml is missing")
    if packaged_files != source_files:
        raise VerificationError(
            f"{chart_name} package contents do not exactly match the release checkout"
        )
    packaged_metadata = chart_metadata(packaged_chart_yaml, f"packaged {chart_name}")
    source_metadata = chart_metadata(source_chart_yaml, f"source {chart_name}")
    if packaged_metadata != source_metadata:
        raise VerificationError(
            f"{chart_name} Chart.yaml metadata does not match the release checkout"
        )
    expected_metadata = {
        "name": chart_name,
        "version": version,
        "appVersion": version,
    }
    for key, value in expected_metadata.items():
        if packaged_metadata.get(key) != value:
            raise VerificationError(f"{chart_name} Chart.yaml {key} must equal {value}")


def expected_source_inputs(source_lock):
    if not isinstance(source_lock, dict) or source_lock.get("schemaVersion") != 3:
        raise VerificationError("source lock must use schemaVersion 3")
    sources = source_lock.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(COMPONENTS[:-1]):
        raise VerificationError("source lock must contain exactly the four public components")
    inputs = {}
    for component in COMPONENTS[:-1]:
        source = sources[component]
        revision = source.get("commit") if isinstance(source, dict) else None
        tag = source.get("releaseTag") if isinstance(source, dict) else None
        if not isinstance(revision, str) or not REVISION_PATTERN.fullmatch(revision):
            raise VerificationError(f"source lock has invalid commit for {component}")
        if not isinstance(tag, str) or not re.fullmatch(
            r"^v[0-9]+\.[0-9]+\.[0-9]+$", tag
        ):
            raise VerificationError(f"source lock has invalid releaseTag for {component}")
        inputs[component] = (revision, tag)
    return inputs


def validate_image(component, image, expected_revision, expected_tag):
    if not isinstance(image, dict) or set(image) != IMAGE_FIELDS:
        raise VerificationError(f"{component} image fields are not exact")
    if image["repository"] != REPOSITORIES[component]:
        raise VerificationError(f"{component} repository is not trusted")
    if image["revision"] != expected_revision:
        raise VerificationError(f"{component} revision does not match release inputs")
    if image["tag"] != expected_tag:
        raise VerificationError(f"{component} tag does not match release inputs")
    if not isinstance(image["digest"], str) or not DIGEST_PATTERN.fullmatch(
        image["digest"]
    ):
        raise VerificationError(f"{component} digest is invalid")
    if image["platforms"] != PLATFORMS:
        raise VerificationError(f"{component} platforms must exactly equal {PLATFORMS}")


def validate_manifests(
    assets,
    source_lock,
    component_preflight_path,
    version,
    platform_revision,
):
    if not REVISION_PATTERN.fullmatch(platform_revision):
        raise VerificationError("platform revision must be a lowercase 40-character SHA")
    expected_inputs = expected_source_inputs(source_lock)
    production = read_json(assets / "production-images.json", "production image manifest")
    if (
        not isinstance(production, dict)
        or set(production) != {"schemaVersion", "version", "images"}
        or production.get("schemaVersion") != 1
        or production.get("version") != version
        or not isinstance(production.get("images"), dict)
        or set(production["images"]) != set(COMPONENTS)
    ):
        raise VerificationError("production-images.json structure or version is not exact")
    for component in COMPONENTS[:-1]:
        revision, tag = expected_inputs[component]
        validate_image(component, production["images"][component], revision, tag)
    validate_image(
        "docs",
        production["images"]["docs"],
        platform_revision,
        f"v{version}",
    )
    docs = read_json(assets / "docs-image.json", "documentation image manifest")
    if docs != production["images"]["docs"]:
        raise VerificationError("docs-image.json must exactly match production images")

    component_preflight = read_json(
        component_preflight_path,
        "verified component preflight",
    )
    if (
        not isinstance(component_preflight, dict)
        or set(component_preflight) != {"schemaVersion", "version", "images"}
        or component_preflight.get("schemaVersion") != 1
        or component_preflight.get("version") != version
        or not isinstance(component_preflight.get("images"), dict)
        or set(component_preflight["images"]) != set(COMPONENTS[:-1])
    ):
        raise VerificationError("component preflight structure or version is not exact")
    for component in COMPONENTS[:-1]:
        if production["images"][component] != component_preflight["images"][component]:
            raise VerificationError(
                f"{component} release image does not match the hash-verified public manifest"
            )

    yaml_lines = ["images:"]
    for component in COMPONENTS:
        yaml_lines.extend(
            (
                f"  {CHART_KEYS[component]}:",
                '    tag: ""',
                f'    digest: "{production["images"][component]["digest"]}"',
            )
        )
    expected_yaml = "\n".join(yaml_lines) + "\n"
    try:
        actual_yaml = (assets / "production-images.yaml").read_bytes().decode()
    except (OSError, UnicodeError) as error:
        raise VerificationError(f"cannot read production-images.yaml: {error}") from error
    if actual_yaml != expected_yaml:
        raise VerificationError("production-images.yaml is not the exact digest-only values")
    return production["images"]["docs"]["digest"]


def validate_release_notes(assets, changelog, version):
    try:
        changelog_lines = changelog.read_bytes().decode().splitlines(keepends=True)
        release_notes = (assets / "release-notes.md").read_bytes().decode()
    except (OSError, UnicodeError) as error:
        raise VerificationError(f"cannot read release notes inputs: {error}") from error
    heading = re.compile(
        rf"^## \[{re.escape(version)}\](?: - [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})?$"
    )
    section = []
    capturing = False
    for line in changelog_lines:
        if heading.fullmatch(line.rstrip("\r\n")):
            if capturing:
                raise VerificationError(
                    f"CHANGELOG contains duplicate {version} release sections"
                )
            capturing = True
        elif capturing and line.startswith("## ["):
            break
        if capturing:
            section.append(line)
    if not section:
        raise VerificationError(f"CHANGELOG does not contain release {version}")
    if release_notes != "".join(section):
        raise VerificationError("release-notes.md does not exactly match CHANGELOG")


def validate_production_render(
    assets,
    application_chart,
    helm,
):
    command = [
        str(helm),
        "template",
        "coderushoj",
        str(application_chart),
        "--namespace",
        "coderushoj",
        "--values",
        str(application_chart / "values-production.yaml"),
        "--values",
        str(assets / "production-images.yaml"),
        "--set",
        "backend.smtp.host=smtp.operator.example",
        "--set",
        "backend.smtp.username=coderushoj@operator.example",
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        expected_render = (assets / "production-render.yaml").read_bytes()
    except OSError as error:
        raise VerificationError(f"cannot rerender production release: {error}") from error
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise VerificationError(f"Helm production rerender failed: {stderr}")
    if result.stdout != expected_render:
        raise VerificationError(
            "production-render.yaml does not exactly match the current chart rerender"
        )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-json", required=True, type=pathlib.Path)
    parser.add_argument("--asset-directory", required=True, type=pathlib.Path)
    parser.add_argument("--version-file", required=True, type=pathlib.Path)
    parser.add_argument("--source-lock", required=True, type=pathlib.Path)
    parser.add_argument("--component-preflight", required=True, type=pathlib.Path)
    parser.add_argument("--platform-revision", required=True)
    parser.add_argument("--changelog", required=True, type=pathlib.Path)
    parser.add_argument("--application-chart", required=True, type=pathlib.Path)
    parser.add_argument("--infrastructure-chart", required=True, type=pathlib.Path)
    parser.add_argument("--helm", default="helm", type=pathlib.Path)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        version = read_version(args.version_file)
        expected_names = expected_asset_names(version)
        validate_asset_directory(args.asset_directory, expected_names)
        validate_checksums(args.asset_directory, expected_names)
        release = read_json(args.release_json, "release API response")
        state = validate_release_metadata(
            release,
            f"v{version}",
            args.asset_directory,
            expected_names,
        )
        validate_chart(
            args.asset_directory,
            args.application_chart,
            "coderushoj",
            version,
        )
        validate_chart(
            args.asset_directory,
            args.infrastructure_chart,
            "coderushoj-infra",
            version,
        )
        docs_digest = validate_manifests(
            args.asset_directory,
            read_json(args.source_lock, "source lock"),
            args.component_preflight,
            version,
            args.platform_revision,
        )
        validate_release_notes(args.asset_directory, args.changelog, version)
        validate_production_render(
            args.asset_directory,
            args.application_chart,
            args.helm,
        )
    except VerificationError as error:
        print(f"existing release verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"state": state, "docsDigest": docs_digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
