#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command kubectl
require_command helm
require_command python3

readonly namespace="${1:-coderushoj}"
readonly diagnostics_root="$CODERUSHOJ_ROOT/.workspace/diagnostics"
readonly bundles_root="$diagnostics_root/bundles"
readonly latest_link="$diagnostics_root/latest"
readonly lock_dir="$diagnostics_root/.publish.lock"
readonly journal_dir="$diagnostics_root/.publish-journal"
readonly lock_timeout_seconds="${CODERUSHOJ_DIAGNOSTICS_LOCK_TIMEOUT_SECONDS:-30}"
readonly stale_lock_seconds="${CODERUSHOJ_DIAGNOSTICS_STALE_LOCK_SECONDS:-5}"
readonly retain_bundles="${CODERUSHOJ_DIAGNOSTICS_RETAIN:-2}"

[[ "$lock_timeout_seconds" =~ ^[1-9][0-9]*$ ]] \
  || die "CODERUSHOJ_DIAGNOSTICS_LOCK_TIMEOUT_SECONDS must be a positive integer"
[[ "$stale_lock_seconds" =~ ^[1-9][0-9]*$ ]] \
  || die "CODERUSHOJ_DIAGNOSTICS_STALE_LOCK_SECONDS must be a positive integer"
[[ "$retain_bundles" =~ ^[1-9][0-9]*$ ]] \
  || die "CODERUSHOJ_DIAGNOSTICS_RETAIN must be a positive integer"

umask 077
mkdir -p "$diagnostics_root"
chmod 700 "$diagnostics_root"

lock_token="$$-${RANDOM}-$(date +%s)"
lock_held="false"
staging_dir=""
temporary_link=""

process_start() {
  ps -p "$1" -o lstart= 2>/dev/null \
    | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

release_lock() {
  if [[ "$lock_held" != "true" || ! -d "$lock_dir" ]]; then
    return
  fi
  local owner_token=""
  owner_token="$(cat "$lock_dir/token" 2>/dev/null || true)"
  if [[ "$owner_token" == "$lock_token" ]]; then
    rm -rf "$lock_dir"
  fi
  lock_held="false"
}

cleanup_process_state() {
  if [[ -n "$staging_dir" && -d "$staging_dir" ]]; then
    rm -rf "$staging_dir"
  fi
  if [[ -n "$temporary_link" && ( -e "$temporary_link" || -L "$temporary_link" ) ]]; then
    rm -f "$temporary_link"
  fi
  release_lock
}

handle_signal() {
  exit "$1"
}

trap cleanup_process_state EXIT
trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM

lock_is_stale() {
  local observed_since="$1"
  local now owner_pid owner_start actual_start
  now="$(date +%s)"
  owner_pid="$(cat "$lock_dir/pid" 2>/dev/null || true)"
  owner_start="$(cat "$lock_dir/process-start" 2>/dev/null || true)"

  if [[ "$owner_pid" =~ ^[1-9][0-9]*$ ]]; then
    if ! kill -0 "$owner_pid" 2>/dev/null; then
      return 0
    fi
    actual_start="$(process_start "$owner_pid")"
    if [[ -n "$owner_start" && -n "$actual_start" ]]; then
      [[ "$owner_start" != "$actual_start" ]] && return 0
      return 1
    fi
  fi

  (( now - observed_since >= stale_lock_seconds ))
}

acquire_lock() {
  local started deadline now observed_since observed_token owner_token quarantine
  started="$(date +%s)"
  deadline="$((started + lock_timeout_seconds))"
  observed_since="$started"
  observed_token=""

  while ! mkdir "$lock_dir" 2>/dev/null; do
    now="$(date +%s)"
    owner_token="$(cat "$lock_dir/token" 2>/dev/null || true)"
    if [[ "$owner_token" != "$observed_token" ]]; then
      observed_token="$owner_token"
      observed_since="$now"
    fi

    if lock_is_stale "$observed_since"; then
      quarantine="$diagnostics_root/.publish.lock.stale.$lock_token"
      if mv "$lock_dir" "$quarantine" 2>/dev/null; then
        rm -rf "$quarantine"
        observed_token=""
        observed_since="$now"
        continue
      fi
    fi

    (( now < deadline )) || die "timed out waiting for diagnostics publish lock"
    sleep 0.05
  done

  chmod 700 "$lock_dir"
  printf '%s\n' "$$" >"$lock_dir/pid"
  process_start "$$" >"$lock_dir/process-start"
  printf '%s\n' "$lock_token" >"$lock_dir/token"
  printf '%s\n' "$started" >"$lock_dir/created"
  chmod 600 "$lock_dir"/*
  lock_held="true"
}

safe_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ && "$1" != "." && "$1" != ".." ]]
}

safe_previous_name() {
  [[ "$1" =~ ^\.legacy\.previous\.[A-Za-z0-9._-]+$ ]]
}

scrub_bundle() {
  local bundle="$1"
  [[ -d "$bundle" && ! -L "$bundle" ]] || die "unsafe diagnostics bundle: $bundle"
  find "$bundle" -type l -exec rm -f {} +
  find "$bundle" -type f -name pods-logs.txt -exec rm -f {} +
  find "$bundle" -type d -exec chmod 700 {} +
  find "$bundle" -type f -exec chmod 600 {} +
}

next_sequence() {
  local sequence_file="$diagnostics_root/.sequence"
  local sequence=0
  if [[ -f "$sequence_file" ]]; then
    sequence="$(cat "$sequence_file")"
    [[ "$sequence" =~ ^[0-9]+$ ]] || sequence=0
  fi
  sequence="$((sequence + 1))"
  printf '%s\n' "$sequence" >"$sequence_file"
  chmod 600 "$sequence_file"
  printf '%s\n' "$sequence"
}

ensure_bundle_sequence() {
  local bundle="$1"
  local sequence=""
  if [[ -f "$bundle/.sequence" ]]; then
    sequence="$(cat "$bundle/.sequence")"
  fi
  if [[ ! "$sequence" =~ ^[1-9][0-9]*$ ]]; then
    sequence="$(next_sequence)"
    printf '%s\n' "$sequence" >"$bundle/.sequence"
  fi
  chmod 600 "$bundle/.sequence"
}

latest_target_name() {
  local target=""
  if [[ -L "$latest_link" ]]; then
    target="$(readlink "$latest_link")"
    if [[ "$target" == bundles/* ]]; then
      target="${target#bundles/}"
      if safe_name "$target" && [[ -d "$bundles_root/$target" ]]; then
        printf '%s\n' "$target"
        return
      fi
    fi
  fi
  return 1
}

publish_pointer() {
  local target_name="$1"
  safe_name "$target_name" || die "unsafe diagnostics pointer target: $target_name"
  [[ -d "$bundles_root/$target_name" ]] \
    || die "diagnostics pointer target is missing: $target_name"
  if [[ -e "$latest_link" && ! -L "$latest_link" ]]; then
    die "refusing to replace non-pointer diagnostics latest"
  fi

  temporary_link="$diagnostics_root/.latest.link.$lock_token"
  ln -s "bundles/$target_name" "$temporary_link"
  python3 - "$temporary_link" "$latest_link" <<'PY'
import os
import sys

os.replace(sys.argv[1], sys.argv[2])
PY
  temporary_link=""
}

write_legacy_journal() {
  local previous_name="$1"
  local target_name="$2"
  mkdir "$journal_dir"
  chmod 700 "$journal_dir"
  printf '%s\n' "legacy-migration" >"$journal_dir/operation"
  printf '%s\n' "$previous_name" >"$journal_dir/previous"
  printf '%s\n' "$target_name" >"$journal_dir/target"
  chmod 600 "$journal_dir"/*
}

newest_bundle_name() {
  local bundle name sequence padded
  local newest_record=""
  for bundle in "$bundles_root"/*; do
    [[ -d "$bundle" && ! -L "$bundle" ]] || continue
    name="${bundle##*/}"
    [[ "$name" != .staging.* ]] || continue
    safe_name "$name" || continue
    ensure_bundle_sequence "$bundle"
    sequence="$(cat "$bundle/.sequence")"
    printf -v padded '%020d' "$sequence"
    if [[ "$padded|$name" > "$newest_record" ]]; then
      newest_record="$padded|$name"
    fi
  done
  [[ -n "$newest_record" ]] || return 1
  printf '%s\n' "${newest_record#*|}"
}

recover_orphan_previous() {
  local previous previous_name target_name recovered_name=""
  for previous in "$diagnostics_root"/.legacy.previous.*; do
    [[ -d "$previous" && ! -L "$previous" ]] || continue
    previous_name="${previous##*/}"
    safe_previous_name "$previous_name" || continue
    target_name="recovered-${previous_name#.legacy.previous.}"
    if [[ -e "$bundles_root/$target_name" ]]; then
      target_name="recovered-${lock_token}-${RANDOM}"
    fi
    scrub_bundle "$previous"
    mv "$previous" "$bundles_root/$target_name"
    ensure_bundle_sequence "$bundles_root/$target_name"
    recovered_name="$target_name"
  done
  if [[ ! -e "$latest_link" && ! -L "$latest_link" && -n "$recovered_name" ]]; then
    publish_pointer "$recovered_name"
  fi
}

recover_legacy_journal() {
  [[ -d "$journal_dir" ]] || return 0
  chmod 700 "$journal_dir"
  find "$journal_dir" -type f -exec chmod 600 {} +

  local operation previous_name target_name previous target
  operation="$(cat "$journal_dir/operation" 2>/dev/null || true)"
  previous_name="$(cat "$journal_dir/previous" 2>/dev/null || true)"
  target_name="$(cat "$journal_dir/target" 2>/dev/null || true)"

  if [[ "$operation" != "legacy-migration" ]] \
    || ! safe_previous_name "$previous_name" \
    || ! safe_name "$target_name"; then
    rm -rf "$journal_dir"
    recover_orphan_previous
    return
  fi

  previous="$diagnostics_root/$previous_name"
  target="$bundles_root/$target_name"

  if [[ "$(latest_target_name 2>/dev/null || true)" == "$target_name" ]]; then
    rm -rf "$journal_dir"
    recover_orphan_previous
    return 0
  fi

  if [[ -d "$latest_link" && ! -L "$latest_link" ]]; then
    scrub_bundle "$latest_link"
    if [[ ! -e "$previous" ]]; then
      mv "$latest_link" "$previous"
    fi
  fi

  if [[ -d "$previous" && ! -L "$previous" ]]; then
    scrub_bundle "$previous"
    if [[ ! -e "$target" ]]; then
      mv "$previous" "$target"
    else
      rm -rf "$previous"
    fi
  fi

  if [[ -d "$target" && ! -L "$target" ]]; then
    scrub_bundle "$target"
    ensure_bundle_sequence "$target"
    if ! latest_target_name >/dev/null 2>&1; then
      publish_pointer "$target_name"
    fi
  fi

  rm -rf "$journal_dir"
  recover_orphan_previous
}

migrate_legacy_latest() {
  [[ -d "$latest_link" && ! -L "$latest_link" ]] || return 0
  scrub_bundle "$latest_link"

  local sequence padded previous_name target_name previous target
  sequence="$(next_sequence)"
  printf -v padded '%020d' "$sequence"
  previous_name=".legacy.previous.$lock_token"
  target_name="legacy-$padded"
  previous="$diagnostics_root/$previous_name"
  target="$bundles_root/$target_name"

  write_legacy_journal "$previous_name" "$target_name"
  mv "$latest_link" "$previous"
  mv "$previous" "$target"
  printf '%s\n' "$sequence" >"$target/.sequence"
  chmod 600 "$target/.sequence"
  publish_pointer "$target_name"
  rm -rf "$journal_dir"
}

recover_persistent_state() {
  mkdir -p "$bundles_root"
  chmod 700 "$bundles_root"
  recover_legacy_journal
  recover_orphan_previous
  migrate_legacy_latest

  local staging newest
  for staging in "$bundles_root"/.staging.*; do
    [[ -d "$staging" ]] || continue
    rm -rf "$staging"
  done

  if ! latest_target_name >/dev/null 2>&1; then
    newest="$(newest_bundle_name || true)"
    if [[ -n "$newest" ]]; then
      publish_pointer "$newest"
    fi
  fi
}

cleanup_old_bundles() {
  local current_name bundle name sequence padded record
  local -a records=()
  local bundle_count=0
  local remove_count=0
  local removed=0
  current_name="$(latest_target_name)"

  for bundle in "$bundles_root"/*; do
    [[ -d "$bundle" && ! -L "$bundle" ]] || continue
    name="${bundle##*/}"
    [[ "$name" != .staging.* ]] || continue
    safe_name "$name" || continue
    ensure_bundle_sequence "$bundle"
    sequence="$(cat "$bundle/.sequence")"
    printf -v padded '%020d' "$sequence"
    records+=("$padded|$name")
    bundle_count="$((bundle_count + 1))"
  done

  remove_count="$((bundle_count - retain_bundles))"
  (( remove_count > 0 )) || return 0

  while IFS= read -r record; do
    name="${record#*|}"
    [[ "$name" != "$current_name" ]] || continue
    rm -rf "${bundles_root:?}/$name"
    removed="$((removed + 1))"
    (( removed >= remove_count )) && break
  done < <(printf '%s\n' "${records[@]}" | sort)
}

acquire_lock
recover_persistent_state

sequence="$(next_sequence)"
printf -v padded_sequence '%020d' "$sequence"
bundle_name="bundle-$padded_sequence"
staging_dir="$(mktemp -d "$bundles_root/.staging.XXXXXX")"
chmod 700 "$staging_dir"

kubectl get nodes -o wide >"$staging_dir/nodes.txt" 2>&1 || true
kubectl get pods,svc,pvc,job -n "$namespace" -o wide >"$staging_dir/workloads.txt" 2>&1 || true
kubectl get gateway,httproute -n "$namespace" -o yaml >"$staging_dir/gateway.yaml" 2>&1 || true
kubectl get events -n "$namespace" --sort-by=.metadata.creationTimestamp >"$staging_dir/events.txt" 2>&1 || true
kubectl describe pods -n "$namespace" >"$staging_dir/pods-describe.txt" 2>&1 || true
helm list -A >"$staging_dir/helm.txt" 2>&1 || true
printf '%s\n' "$sequence" >"$staging_dir/.sequence"
scrub_bundle "$staging_dir"

mv "$staging_dir" "$bundles_root/$bundle_name"
staging_dir=""
publish_pointer "$bundle_name"
cleanup_old_bundles
release_lock

log "sensitive diagnostics published through $latest_link"
