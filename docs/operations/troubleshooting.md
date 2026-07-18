# 故障排查

先采集脱敏诊断，再做变更：

```bash
make diagnostics
kubectl get events -n coderushoj --sort-by=.metadata.creationTimestamp
```

诊断输出位于 `.workspace/diagnostics/latest/`，不包含 Secret 内容。

## Colima 与镜像拉取

若出现 `lookup registry-1.docker.io on [::1]:53`，执行 `make cluster-up`；脚本会检测损坏的 Colima `/etc/resolv.conf` 并修复。仍失败时：

```bash
colima ssh -- cat /etc/resolv.conf
docker pull kindest/node:v1.36.1
```

## MySQL

```bash
kubectl logs -n coderushoj statefulset/coderushoj-infra-mysql --tail=200
kubectl exec -n coderushoj statefulset/coderushoj-infra-mysql -- \
  /bin/sh -ec 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqladmin ping -uroot'
```

首次初始化失败后不要直接删除 PVC；先确认是否有业务数据并完成备份。密钥文件不应包含换行，生成脚本会自动规范化。

## Redis

```bash
kubectl logs -n coderushoj statefulset/coderushoj-infra-redis --tail=200
kubectl exec -n coderushoj statefulset/coderushoj-infra-redis -- \
  /bin/sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping'
```

Redis 丢失不应造成业务数据丢失；恢复后由 MySQL 重建缓存与榜单。

## RocketMQ

```bash
kubectl logs -n coderushoj deployment/coderushoj-infra-rocketmq-namesrv --tail=200
kubectl logs -n coderushoj statefulset/coderushoj-infra-rocketmq-broker --tail=200
kubectl exec -n coderushoj statefulset/coderushoj-infra-rocketmq-broker -- \
  sh mqadmin topicList -n coderushoj-infra-rocketmq-namesrv:9876
```

官方 Broker 默认 JVM 需要约 2 GiB 堆并预触碰内存；本地值已固定为 512 MiB。若出现 `OOMKilled`，确认 `HEAP_OPTS` 是否被覆盖，并同时检查容器 limit 与节点可用内存。

## SeaweedFS

```bash
kubectl logs -n coderushoj statefulset/coderushoj-infra-seaweedfs --tail=200
kubectl get svc coderushoj-infra-seaweedfs -n coderushoj
kubectl delete job coderushoj-s3-smoke -n coderushoj --ignore-not-found
make smoke
```

S3 冒烟测试会上传并读取 `coderushoj-testdata/smoke/platform.txt`，不会删除其他对象。

## Envoy Gateway

```bash
kubectl get gatewayclass,gateway,httproute -A
kubectl describe gateway coderushoj -n coderushoj
kubectl logs -n envoy-gateway-system deployment/envoy-gateway --tail=200
```

Gateway 应为 `Programmed=True`。应用镜像尚未接入或 Service 不存在时，HTTPRoute 会显示 `ResolvedRefs=False`；这与入口控制器故障是两类问题。

## 一键重试前

不要把删除 namespace/PVC 当作通用修复。先备份、确认资源所有权、记录 Helm revision，再执行 `helm upgrade` 或 `helm rollback`。
