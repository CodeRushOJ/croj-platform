#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 <owner/repository> <tag> <output-json>" >&2
  exit 2
fi

repository="$1"
tag="$2"
output_json="$3"

[[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || {
  echo "invalid GitHub repository: $repository" >&2
  exit 2
}
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "invalid release tag: $tag" >&2
  exit 2
}
[[ -n "$output_json" ]] || {
  echo "release metadata output path must not be empty" >&2
  exit 2
}

lookup_error="$(mktemp)"
if release_api_url="$(
  gh release view "$tag" \
    --repo "$repository" \
    --json apiUrl \
    --jq .apiUrl \
    2>"$lookup_error"
)"; then
  expected_prefix="https://api.github.com/repos/$repository/releases/"
  release_id="${release_api_url#"$expected_prefix"}"
  if [[ "$release_api_url" != "$expected_prefix$release_id" ]] ||
    [[ ! "$release_id" =~ ^[1-9][0-9]*$ ]]
  then
    echo "release lookup returned an unsafe apiUrl: $release_api_url" >&2
    exit 1
  fi
  metadata_temporary="${output_json}.tmp.$$"
  gh api "$release_api_url" > "$metadata_temporary"
  mv "$metadata_temporary" "$output_json"
  exit 0
else
  lookup_status="$?"
fi

if [[ "$lookup_status" -eq 1 ]] &&
  grep -Fxq 'release not found' "$lookup_error"
then
  exit 3
fi

cat "$lookup_error" >&2
exit 1
