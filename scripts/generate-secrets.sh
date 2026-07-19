#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

require_command openssl

readonly target="${1:-coderushoj}"
readonly secret_name="${CODERUSHOJ_SECRET_NAME:-coderushoj-local-secrets}"
readonly secret_dir="$CODERUSHOJ_ROOT/.workspace/secrets"

if [[ "$target" != "--files-only" ]]; then
  require_command kubectl
fi

write_random_secret() {
  local path="$1"
  local bytes="$2"
  local secret_value
  if [[ ! -f "$path" ]]; then
    openssl rand -hex "$bytes" | tr -d '\r\n' >"$path"
  fi
  secret_value="$(tr -d '\r\n' <"$path")"
  [[ -n "$secret_value" ]] || die "generated secret is empty: $path"
  printf '%s' "$secret_value" >"$path"
  chmod 600 "$path"
}

write_random_base64_secret() {
  local path="$1"
  local bytes="$2"
  local secret_value
  local decoded_bytes
  if [[ ! -f "$path" ]]; then
    openssl rand -base64 "$bytes" | tr -d '\r\n' >"$path"
  fi
  secret_value="$(tr -d '\r\n' <"$path")"
  decoded_bytes="$(printf '%s' "$secret_value" | openssl base64 -d -A | wc -c | tr -d ' ')"
  [[ "$decoded_bytes" == "$bytes" ]] \
    || die "base64 secret must decode to $bytes bytes: $path"
  printf '%s' "$secret_value" >"$path"
  chmod 600 "$path"
}

write_literal_secret() {
  local path="$1"
  local value="$2"
  if [[ ! -f "$path" ]]; then
    printf '%s' "$value" >"$path"
  fi
  [[ -s "$path" ]] || die "generated secret is empty: $path"
  chmod 600 "$path"
}

mkdir -p "$secret_dir"
chmod 700 "$secret_dir"

if [[ ! -f "$secret_dir/mysql-username" ]]; then
  printf '%s' 'coderushoj' >"$secret_dir/mysql-username"
  chmod 600 "$secret_dir/mysql-username"
fi
write_random_secret "$secret_dir/mysql-password" 24
write_random_secret "$secret_dir/mysql-root-password" 24
write_random_secret "$secret_dir/redis-password" 24
write_random_secret "$secret_dir/s3-access-key" 12
write_random_secret "$secret_dir/s3-secret-key" 32
write_random_secret "$secret_dir/jwt-secret" 32
write_random_secret "$secret_dir/judge-result-service-token" 32
write_random_secret "$secret_dir/smtp-password" 24
write_random_base64_secret "$secret_dir/external-api-auth-pepper-base64" 32
write_random_base64_secret "$secret_dir/external-idempotency-pepper-base64" 32
write_random_base64_secret "$secret_dir/external-cursor-key-base64" 32
write_random_base64_secret "$secret_dir/external-source-key-base64" 32
write_literal_secret "$secret_dir/bootstrap-admin-username" "admin"
write_literal_secret "$secret_dir/bootstrap-admin-email" "admin@coderushoj.local"
write_random_secret "$secret_dir/bootstrap-admin-password" 24

if [[ "$target" == "--files-only" ]]; then
  log "local secret files are ready in $secret_dir"
  exit 0
fi

kubectl create namespace "$target" --dry-run=client --output=yaml \
  | kubectl apply --filename - >/dev/null

kubectl create secret generic "$secret_name" \
  --namespace "$target" \
  --from-file=mysql-username="$secret_dir/mysql-username" \
  --from-file=mysql-password="$secret_dir/mysql-password" \
  --from-file=mysql-root-password="$secret_dir/mysql-root-password" \
  --from-file=redis-password="$secret_dir/redis-password" \
  --from-file=s3-access-key="$secret_dir/s3-access-key" \
  --from-file=s3-secret-key="$secret_dir/s3-secret-key" \
  --from-file=jwt-secret="$secret_dir/jwt-secret" \
  --from-file=judge-result-service-token="$secret_dir/judge-result-service-token" \
  --from-file=smtp-password="$secret_dir/smtp-password" \
  --from-file=external-api-auth-pepper-base64="$secret_dir/external-api-auth-pepper-base64" \
  --from-file=external-idempotency-pepper-base64="$secret_dir/external-idempotency-pepper-base64" \
  --from-file=external-cursor-key-base64="$secret_dir/external-cursor-key-base64" \
  --from-file=external-source-key-base64="$secret_dir/external-source-key-base64" \
  --dry-run=client \
  --output=yaml \
  | kubectl apply --filename - >/dev/null

log "local Kubernetes secret $target/$secret_name is ready"
