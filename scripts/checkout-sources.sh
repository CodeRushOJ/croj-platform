#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

lock_file="$CODERUSHOJ_ROOT/config/source-lock.json"
sources_root="${CODERUSHOJ_SOURCES_DIR:-$CODERUSHOJ_ROOT/.workspace/sources}"

while (($# > 0)); do
  case "$1" in
    --lock)
      (($# >= 2)) || die "--lock requires a path"
      lock_file="$2"
      shift 2
      ;;
    --root)
      (($# >= 2)) || die "--root requires a path"
      sources_root="$2"
      shift 2
      ;;
    *) die "usage: $0 [--lock PATH] [--root DIRECTORY]" ;;
  esac
done

require_command git
require_command python3
python3 "$SCRIPT_DIR/verify-source-lock.py" validate --lock "$lock_file" >/dev/null

mkdir -p "$sources_root/.tmp"
sources_root="$(cd "$sources_root" && pwd)"
lock_timeout_ms="${CODERUSHOJ_CHECKOUT_LOCK_TIMEOUT_MS:-300000}"
lock_poll_ms="${CODERUSHOJ_CHECKOUT_LOCK_POLL_MS:-50}"
legacy_lock_grace_ms="${CODERUSHOJ_CHECKOUT_LOCK_LEGACY_GRACE_MS:-1000}"

[[ "$lock_timeout_ms" =~ ^[1-9][0-9]*$ ]] || die "checkout lock timeout must be positive milliseconds"
[[ "$lock_poll_ms" =~ ^[1-9][0-9]*$ ]] || die "checkout lock poll interval must be positive milliseconds"
[[ "$legacy_lock_grace_ms" =~ ^[1-9][0-9]*$ ]] || die "legacy lock grace must be positive milliseconds"
((legacy_lock_grace_ms >= lock_poll_ms)) || die "legacy lock grace must be at least one poll interval"

verify_checkout() {
  local component="$1"
  local commit="$2"
  local context="$3"
  local dockerfile="$4"
  local checkout_directory="$5"
  local actual_commit

  [[ -d "$checkout_directory/.git" ]] || die "$component checkout is not a Git repository: $checkout_directory"
  actual_commit="$(git -C "$checkout_directory" rev-parse HEAD)"
  [[ "$actual_commit" == "$commit" ]] || die "$component checkout has $actual_commit, expected $commit"
  if git -C "$checkout_directory" symbolic-ref --quiet HEAD >/dev/null; then
    die "$component checkout is not detached: $checkout_directory"
  fi
  [[ -z "$(git -C "$checkout_directory" status --porcelain --untracked-files=all)" ]] || \
    die "$component checkout is not clean: $checkout_directory"
  [[ -f "$checkout_directory/$context/$dockerfile" ]] || \
    die "$component Dockerfile is missing: $checkout_directory/$context/$dockerfile"
}

run_locked_checkout() {
  local lock_directory="$1"
  shift
  python3 "$SCRIPT_DIR/checkout-lock.py" \
    --lock "$lock_directory" \
    --parent-pid "$$" \
    --timeout-ms "$lock_timeout_ms" \
    --poll-ms "$lock_poll_ms" \
    --legacy-grace-ms "$legacy_lock_grace_ms" \
    -- "$SCRIPT_DIR/checkout-one-source.sh" "$@"
}

record_count=0
while IFS= read -r -d '' component; do
  IFS= read -r -d '' repository || die "source lock record is truncated after component"
  IFS= read -r -d '' commit || die "source lock record is truncated after repository"
  IFS= read -r -d '' context || die "source lock record is truncated after commit"
  IFS= read -r -d '' dockerfile || die "source lock record is truncated after context"
  IFS= read -r -d '' _image || die "source lock record is truncated after dockerfile"
  record_count=$((record_count + 1))
  component_root="$sources_root/$component"
  checkout_directory="$component_root/$commit"
  lock_directory="$component_root/.${commit}.lock"
  mkdir -p "$component_root"

  if [[ -e "$checkout_directory" ]]; then
    verify_checkout "$component" "$commit" "$context" "$dockerfile" "$checkout_directory"
    log "reusing $component at $commit"
    continue
  fi

  run_locked_checkout \
    "$lock_directory" \
    "$component" \
    "$repository" \
    "$commit" \
    "$context" \
    "$dockerfile" \
    "$checkout_directory" \
    "$sources_root"
done < <(python3 "$SCRIPT_DIR/verify-source-lock.py" "records" --lock "$lock_file")
[[ "$record_count" -eq 5 ]] || die "source lock yielded $record_count records, expected 5"
