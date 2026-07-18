#!/usr/bin/env bash
set -Eeuo pipefail

CODERUSHOJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CODERUSHOJ_ROOT
export CODERUSHOJ_ROOT

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

helm_rollback_flag() {
  local helm_version
  helm_version="$(helm version --template '{{.Version}}')" || die "unable to determine Helm version"
  case "$helm_version" in
    v3.*)
      printf '%s\n' '--atomic'
      ;;
    v4.*)
      printf '%s\n' '--rollback-on-failure'
      ;;
    *)
      die "unsupported Helm version: $helm_version"
      ;;
  esac
}
