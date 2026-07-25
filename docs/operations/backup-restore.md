# 备份与恢复

备份必须和应用版本、数据库 schema 版本、镜像 digest 一起记录。仅有文件而没有恢复演练不算有效备份。

## MySQL

```bash
mkdir -p .workspace/backups/mysql
kubectl exec -n coderushoj statefulset/coderushoj-infra-mysql -- \
  /bin/sh -ec 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --events --all-databases' \
  > .workspace/backups/mysql/all.sql
```

恢复到隔离的验证实例，确认无误后再切换业务流量：

```bash
kubectl exec -i -n coderushoj statefulset/coderushoj-infra-mysql -- \
  /bin/sh -ec 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot' \
  < .workspace/backups/mysql/all.sql
```

## Redis

Redis 不是权威数据源。可执行 `BGSAVE` 保存加速层快照，但灾难恢复优先从 MySQL 重建：

```bash
kubectl exec -n coderushoj statefulset/coderushoj-infra-redis -- \
  /bin/sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli BGSAVE'
```

## RocketMQ

停止发布新提交，等待消费 lag 降为零，再对 Broker PVC 做存储快照。恢复后校验 NameServer 注册、两个主题和消费组 offset；不要只复制运行中的目录而忽略一致性。

```bash
kubectl exec -n coderushoj statefulset/coderushoj-infra-rocketmq-broker -- \
  sh mqadmin topicList -n coderushoj-infra-rocketmq-namesrv:9876
```

## SeaweedFS

本地环境可对 PVC 做 CSI/卷级快照；生产环境应使用 SeaweedFS 复制或 S3 级离站同步。至少抽样验证隐藏测试包的对象大小、校验和与不可变版本键。

## 恢复验证

在独立 namespace 或临时集群完成以下检查：

1. MySQL 执行 `SELECT 1`，核对 Flyway schema 版本与关键行数；
2. Redis 返回 `PONG`，清空后系统仍能从 MySQL 重建核心页面；
3. RocketMQ 存在 `submission-topic` 和死信主题，测试消息只被结算一次；
4. SeaweedFS 能读取已知测试包并通过 SHA-256 校验；
5. 执行 `make smoke`，随后通过前端完成至少一条真实提交并确认结果为 `ACCEPTED`；生产恢复演练还应逐一抽样所有已启用语言；
6. 记录恢复点、耗时、数据损失窗口和验证人。

密钥备份必须使用独立的加密密钥管理系统；不要把 `.workspace/secrets/` 或解密后的 Kubernetes Secret 提交到 Git。
