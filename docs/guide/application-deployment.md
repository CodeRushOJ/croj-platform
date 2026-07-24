# 应用服务 Kubernetes 部署

应用 Chart 一次部署 Frontend、Backend、Judging Server、Sandbox 和 Docs。默认 `applications.enabled=false`，因此不带 profile 的 `helm template` 或安装不会拉取尚未发布的应用镜像。Kind 验收使用 `values-kind-app.yaml` 显式启用全部应用并要求预先载入 `:dev` 镜像；生产使用 `values-production.yaml`，五个镜像都必须提供不可变 digest。

## 安装前检查

以下命令只校验源码锁、Chart 与渲染，不修改集群：

```bash
make source-verify
helm lint charts/coderushoj-infra
helm lint charts/coderushoj
helm template coderushoj charts/coderushoj \
  --namespace coderushoj \
  --values charts/coderushoj/values-kind.yaml \
  --values charts/coderushoj/values-kind-app.yaml >/tmp/coderushoj-app.yaml
```

`config/source-lock.json` 只锁定 Frontend、Backend、Judging 和 Sandbox 四个外部开发镜像。Docs 镜像从当前平台 checkout 构建，并以当前 `GITHUB_SHA`（本地为 `HEAD`）作为 OCI revision。完整 Kind 流程必须先运行 `make source-checkout && make images-build && make images-load`；不要用可变分支替换锁中的 40 位提交，也不要用旧平台 revision 替代当前 Docs 内容。

应用依赖 MySQL、Redis、RocketMQ、S3 兼容对象存储和 SMTP。参考集群通过 infra Chart 提供 MySQL、Redis、RocketMQ、SeaweedFS 和 Mailpit。生产环境可以使用托管服务，但 `dependencies.*` 地址、端口、桶和 region 必须与实际环境一致。

## Secret 合同

Chart 只引用 `secrets.name` 指定的现有 Secret，不在 values 或渲染清单中保存明文。开发者独占集群可运行：

```bash
scripts/generate-secrets.sh coderushoj
```

`scripts/generate-secrets.sh` 把随机值写入 Git 忽略且权限为 `0600` 的 `.workspace/secrets/`，再创建 `coderushoj-local-secrets`。生产不要复用本地文件；应由 Secret 管理系统创建 `coderushoj-production-secrets`，并提供这些 key：

```text
mysql-username
mysql-password
redis-password
s3-access-key
s3-secret-key
jwt-secret
judge-result-service-token
smtp-password
external-api-auth-pepper-base64
external-idempotency-pepper-base64
external-cursor-key-base64
external-source-key-base64
```

四个 `*-base64` key 必须各自解码为 32 字节。Backend 和 Judging 必须共享同一个 `judge-result-service-token`。检查 key 名时只读取元数据，不要执行会打印 Secret 值的命令。

## 服务发现与数据流

Backend 通过 MySQL 保存权威业务数据，Redis 只承载可重建状态，RocketMQ 传递提交任务。隐藏 TestBundle 由 Backend 写入私有 S3 桶，Judging 从相同桶读取；对象存储凭据只来自 Secret。

Judging 的内部回调目标由 `BACKEND_INTERNAL_URL` 渲染为 `http://croj-backend:7999/api`。Sandbox 不再依赖 Kubernetes API 权限或手工 Endpoint 列表，`SANDBOX_GRPC_TARGET` 使用 `dns:///sandbox-workers.coderushoj.svc.cluster.local:50051`；gRPC 客户端通过 `round_robin` 使用 headless Service 的 Ready Endpoint。

Gateway 暴露三个主机：

- `gateway.host`：Frontend 和 `/api` Backend；
- `gateway.docsHost`：静态 Docs；
- `gateway.judgeHost`：仅在 `judgingServer.externalAPI.enabled=true` 且 `expose=true` 时暴露异步 Judge REST。

先运行 checksum 固定的 `scripts/install-gateway.sh`，再安装 infra 和 application release。Envoy Gateway controller/CRD 不属于这两个 Helm release，应用回滚不会回滚或删除它们。

## Kind 开发部署

以下路径会启动真实工作负载，只能用于独占测试集群：

```bash
scripts/install-gateway.sh
scripts/generate-secrets.sh coderushoj

helm upgrade --install coderushoj-infra charts/coderushoj-infra \
  --namespace coderushoj --create-namespace \
  --rollback-on-failure --wait --wait-for-jobs --timeout 15m

helm upgrade --install coderushoj charts/coderushoj \
  --namespace coderushoj \
  --values charts/coderushoj/values-kind.yaml \
  --values charts/coderushoj/values-kind-app.yaml \
  --rollback-on-failure --wait --timeout 15m
```

验证：

```bash
kubectl get deploy,svc,endpointslice -n coderushoj
kubectl rollout status deployment/croj-frontend -n coderushoj
kubectl rollout status deployment/croj-backend -n coderushoj
kubectl rollout status deployment/croj-judging-server -n coderushoj
kubectl rollout status deployment/croj-sandbox -n coderushoj
kubectl rollout status deployment/croj-docs -n coderushoj
```

完整真实登录、管理端 TestBundle、FPS、两条判题链、社区、比赛和邮件验收见[三节点产品 E2E](../operations/product-e2e.md)。

## 生产 values

生产必须为全部镜像填写 digest，不能只用 tag：

```yaml
applications:
  enabled: true
secrets:
  name: coderushoj-production-secrets
images:
  frontend:
    digest: sha256:FRONTEND_DIGEST
  backend:
    digest: sha256:BACKEND_DIGEST
  judgingServer:
    digest: sha256:JUDGING_DIGEST
  sandbox:
    digest: sha256:SANDBOX_DIGEST
  docs:
    digest: sha256:DOCS_DIGEST
backend:
  corsAllowedOrigins: https://oj.example.com
  smtp:
    host: smtp.example.com
    username: oj@example.com
```

对应键是 `images.frontend.digest`、`images.backend.digest`、`images.judgingServer.digest`、`images.sandbox.digest` 和 `images.docs.digest`。每个值都必须是 `sha256:` 加 64 位小写十六进制；示例占位符必须替换，否则 schema 会 fail closed。

先把环境覆盖保存为不含 Secret 的 `application-production-values.yaml`，离线渲染并通过 kubeconform，再安装：

```bash
helm template coderushoj charts/coderushoj \
  --namespace coderushoj \
  --values charts/coderushoj/values-production.yaml \
  --values application-production-values.yaml \
  | kubeconform -strict -summary -ignore-missing-schemas

helm upgrade --install coderushoj charts/coderushoj \
  --namespace coderushoj \
  --values charts/coderushoj/values-production.yaml \
  --values application-production-values.yaml \
  --rollback-on-failure --wait --timeout 15m
```

生产发布前还必须确认 Gateway TLS Secret、真实 SMTP TLS 模式、备份、容量和支持 NetworkPolicy 的 CNI。

## 一次性超级管理员

`adminBootstrap.enabled` 默认关闭。只在初次安装且已经创建独立 bootstrap Secret 时临时启用；Job 使用正式 Backend 镜像的 `CROJ_MODE=bootstrap-admin`，只获得 DNS 与 MySQL 网络权限。成功后立刻再次 Helm upgrade 关闭该值，并删除 bootstrap Secret。长期 Backend Deployment 不应引用这份凭据。CI 中可审计的完整实现见 `scripts/deploy-product-e2e.sh`。

## 回滚

先查看历史，再只回滚应用 release：

```bash
helm history coderushoj -n coderushoj
helm rollback coderushoj PREVIOUS_REVISION -n coderushoj --wait
kubectl rollout status deployment/croj-backend -n coderushoj --timeout=5m
```

回滚镜像不会自动回滚 MySQL migration、S3 TestBundle、上传文件或 Secret。执行前按[备份与恢复](../operations/backup-restore.md)完成备份和恢复演练。不要在普通应用回滚中删除 Gateway API 或 Envoy Gateway CRD。
