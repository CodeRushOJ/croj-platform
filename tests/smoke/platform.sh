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

mysql_result=""
for mysql_attempt in {1..30}; do
  # Expansion is intentionally performed inside the target container.
  # shellcheck disable=SC2016
  if mysql_result="$(kubectl exec --namespace "$namespace" statefulset/coderushoj-infra-mysql -- \
    /bin/sh -ec 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --protocol=TCP --host=127.0.0.1 --skip-column-names --execute "SELECT 1"' 2>/dev/null)" \
    && [[ "$mysql_result" == "1" ]]; then
    break
  fi
  if [[ "$mysql_attempt" == "30" ]]; then
    die "MySQL TCP smoke query failed after 30 attempts"
  fi
  sleep 2
done

# Expansion is intentionally performed inside the target container.
# shellcheck disable=SC2016
redis_result="$(kubectl exec --namespace "$namespace" statefulset/coderushoj-infra-redis -- \
  /bin/sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping')"
[[ "$redis_result" == "PONG" ]] || die "Redis smoke command failed"

rocketmq_topics="$(kubectl exec --namespace "$namespace" \
  statefulset/coderushoj-infra-rocketmq-broker -- \
  sh mqadmin topicList -n coderushoj-infra-rocketmq-namesrv:9876)"
grep -Fxq submission-topic <<<"$rocketmq_topics" \
  || die "RocketMQ submission topic is missing"

kubectl delete job coderushoj-s3-smoke --namespace "$namespace" --ignore-not-found >/dev/null
kubectl apply --filename "$SCRIPT_DIR/s3-job.yaml" >/dev/null
kubectl wait --namespace "$namespace" --for=condition=Complete \
  job/coderushoj-s3-smoke --timeout=300s

kubectl wait --namespace "$namespace" --for=condition=Programmed \
  gateway/coderushoj --timeout=120s

running_images="$(kubectl get pods --namespace "$namespace" \
  --output=jsonpath='{range .items[*].spec.containers[*]}{.image}{"\n"}{end}')"
if grep -Eq '(^|:)latest$' <<<"$running_images"; then
  die "a running Pod uses an unpinned latest image"
fi

log "platform smoke tests: PASS"
