#!/usr/bin/env bash
set -Eeuo pipefail

CODERUSHOJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CODERUSHOJ_ROOT
export CODERUSHOJ_ROOT
readonly CODERUSHOJ_PLATFORM_REPOSITORY="https://github.com/CodeRushOJ/croj-platform.git"
readonly CODERUSHOJ_DOCS_DEV_IMAGE="ghcr.io/coderushoj/coderushoj-docs:dev"
export CODERUSHOJ_PLATFORM_REPOSITORY CODERUSHOJ_DOCS_DEV_IMAGE

log() {
  printf '[coderushoj] %s\n' "$*"
}

die() {
  printf '[coderushoj] error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

current_platform_revision() {
  local checkout_revision requested_revision status
  require_command git
  checkout_revision="$(git -C "$CODERUSHOJ_ROOT" rev-parse HEAD)" || \
    die "cannot resolve the current platform checkout revision"
  status="$(git -C "$CODERUSHOJ_ROOT" status --porcelain --untracked-files=all)" || \
    die "cannot inspect the current platform checkout"
  [[ -z "$status" ]] || \
    die "current platform checkout is not clean; commit all tracked, staged, and untracked changes before building Docs"
  requested_revision="${GITHUB_SHA:-$checkout_revision}"
  [[ "$requested_revision" =~ ^[0-9a-f]{40}$ ]] || \
    die "current platform revision must be a lowercase 40-character Git object ID"
  [[ "$requested_revision" == "$checkout_revision" ]] || \
    die "GITHUB_SHA does not match the current platform checkout"
  printf '%s\n' "$requested_revision"
}
