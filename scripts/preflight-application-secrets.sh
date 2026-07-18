#!/usr/bin/env bash
set -Eeuo pipefail

namespace="coderushoj"
secret_name=""
required_keys=()

usage() {
  printf '%s\n' \
    "Usage: $0 --secret NAME --required-key KEY [--required-key KEY ...] [--namespace NAMESPACE]" \
    "Checks an existing Kubernetes Secret without printing its values."
}

while (($# > 0)); do
  case "$1" in
    --namespace)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      namespace="$2"
      shift 2
      ;;
    --secret)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      secret_name="$2"
      shift 2
      ;;
    --required-key)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      required_keys+=("$2")
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "$secret_name" ]] || { printf '%s\n' "--secret is required" >&2; exit 2; }
((${#required_keys[@]} > 0)) || { printf '%s\n' "at least one --required-key is required" >&2; exit 2; }

if ! kubectl get secret "$secret_name" --namespace "$namespace" >/dev/null; then
  printf 'Secret %s/%s does not exist or is not readable\n' "$namespace" "$secret_name" >&2
  exit 1
fi

for required_key in "${required_keys[@]}"; do
  if [[ ! "$required_key" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'invalid Secret key name: %s\n' "$required_key" >&2
    exit 2
  fi
  secret_value="$(kubectl get secret "$secret_name" --namespace "$namespace" -o "jsonpath={.data.${required_key}}")"
  if [[ -z "$secret_value" ]]; then
    printf 'Secret %s/%s is missing required non-empty key %s\n' "$namespace" "$secret_name" "$required_key" >&2
    exit 1
  fi
done

printf 'Secret %s/%s passed required-key preflight (%d keys)\n' \
  "$namespace" "$secret_name" "${#required_keys[@]}"
