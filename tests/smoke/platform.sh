#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/lib.sh
source "$ROOT_DIR/scripts/lib.sh"

require_command kubectl

readonly namespace="coderushoj"

for workload in mysql redis rocketmq-broker seaweedfs; do
  kubectl rollout status "statefulset/coderushoj-infra-$workload" \
    --namespace "$namespace" --timeout=300s
done
kubectl rollout status deployment/coderushoj-infra-rocketmq-namesrv \
  --namespace "$namespace" --timeout=300s

# Expansion is intentionally performed inside the target container.
# shellcheck disable=SC2016
mysql_result="$(kubectl exec --namespace "$namespace" statefulset/coderushoj-infra-mysql -- \
  /bin/sh -ec 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --skip-column-names --execute "SELECT 1"')"
[[ "$mysql_result" == "1" ]] || die "MySQL smoke query failed"

# Expansion is intentionally performed inside the target container.
# shellcheck disable=SC2016
redis_result="$(kubectl exec --namespace "$namespace" statefulset/coderushoj-infra-redis -- \
  /bin/sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping')"
[[ "$redis_result" == "PONG" ]] || die "Redis smoke command failed"

kubectl exec --namespace "$namespace" statefulset/coderushoj-infra-rocketmq-broker -- \
  sh mqadmin topicList -n coderushoj-infra-rocketmq-namesrv:9876 \
  | grep -Fxq submission-topic

kubectl delete job coderushoj-s3-smoke --namespace "$namespace" --ignore-not-found >/dev/null
kubectl apply --filename "$SCRIPT_DIR/s3-job.yaml" >/dev/null
kubectl wait --namespace "$namespace" --for=condition=Complete \
  job/coderushoj-s3-smoke --timeout=300s

kubectl wait --namespace "$namespace" --for=condition=Programmed \
  gateway/coderushoj --timeout=120s

if kubectl get pods --namespace "$namespace" \
  --output=jsonpath='{range .items[*].spec.containers[*]}{.image}{"\n"}{end}' \
  | grep -Eq '(^|:)latest$'; then
  die "a running Pod uses an unpinned latest image"
fi

log "platform smoke tests: PASS"
