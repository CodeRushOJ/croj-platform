# 安装与部署

CodeRushOJ 提供两条路径：Docker Compose 用于单机开发和快速体验；三节点 Kind + Helm 用于验证生产形态、Kubernetes 调度和判题沙箱。用户不需要在宿主机安装 Java、Go、Node、MySQL、Redis 或 RocketMQ。

## 前置条件

macOS 推荐 Colima；Linux 可直接使用 Docker Engine。仓库的 `Brewfile` 固定了本地工具清单。

```bash
brew bundle --file Brewfile
colima start --cpu 6 --memory 8 --disk 50 --arch aarch64 --vm-type vz
```

Homebrew 的 Compose 与 Buildx 是 Docker CLI 插件。Apple Silicon 默认插件目录为 `/opt/homebrew/lib/docker/cli-plugins`，Intel Mac 通常为 `/usr/local/lib/docker/cli-plugins`。将实际的 `$(brew --prefix)/lib/docker/cli-plugins` 合并到 `~/.docker/config.json`：

```json
{
  "cliPluginsExtraDirs": [
    "/opt/homebrew/lib/docker/cli-plugins"
  ]
}
```

验证工具：

```bash
docker --version
docker compose version
docker buildx version
kubectl version --client
kind version
helm version
shellcheck --version
```

## 路径 A：Docker Compose

生成只保存在 `.workspace/secrets/` 的本地密钥，并启动固定版本依赖：

```bash
./scripts/generate-secrets.sh --files-only
docker compose up -d --wait
# 等价封装
make compose-up
```

默认仅绑定环回地址：MySQL `127.0.0.1:3306`、Redis `127.0.0.1:6379`、SeaweedFS S3 `127.0.0.1:8333`。查看状态与日志：

```bash
docker compose ps
docker compose logs --tail=100 mysql redis rocketmq-broker seaweedfs
```

停止但保留数据卷：

```bash
make compose-down
```

`docker compose down --volumes` 会永久删除本机开发数据，只有明确需要重建空环境时才使用。

## 路径 B：Kubernetes 标准部署

一条完整的本地部署链路：

```bash
make bootstrap
make cluster-up
make deploy
make smoke
```

基础命令不会尝试拉取尚未发布的应用镜像。开发者完成五个本地镜像构建并载入 Kind 后，再显式启用应用 profile：

```bash
kind load docker-image \
  ghcr.io/coderushoj/croj-frontend:dev \
  ghcr.io/coderushoj/croj-backend:dev \
  ghcr.io/coderushoj/croj-judging-server:dev \
  ghcr.io/coderushoj/croj-sandbox:dev \
  ghcr.io/coderushoj/coderushoj-docs:dev \
  --name coderushoj
helm upgrade --install coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --values ./charts/coderushoj/values-kind.yaml \
  --values ./charts/coderushoj/values-kind-app.yaml \
  --rollback-on-failure --wait --timeout 10m
```

`values-kind-app.yaml` 使用 `imagePullPolicy: Never`，任何未加载镜像都会立即暴露为部署错误，不会悄悄从不可信标签拉取。跨仓库集成 CI 会在发布前替代这段人工加载流程。

### 创建首个管理员

全新数据库没有默认密码，普通注册也不会自动获得管理权限。后端镜像已部署且 MySQL Ready 后执行：

```bash
scripts/bootstrap-admin.sh
```

本地身份固定为 `admin` / `admin@coderushoj.local`，随机密码只写入 Git 忽略且权限为 `0600` 的 `.workspace/secrets/bootstrap-admin-password`。脚本不会打印密码；需要登录时在自己的终端读取该文件。Job 使用专门的 `coderushoj-admin-bootstrap-secret`，只允许 DNS 和 MySQL egress，既不挂 ServiceAccount token，也不把 bootstrap 变量注入长期 Backend Deployment。成功 Job 最多保留十分钟供审计，验证登录后删除身份 Secret：

```bash
kubectl delete secret coderushoj-admin-bootstrap-secret -n coderushoj
```

相同身份的后端命令是幂等的，不会重置密码。若需要在修复配置后明确重建 Job，先保留失败日志，再运行 `scripts/bootstrap-admin.sh --rerun`；该参数只删除精确的 `coderushoj/coderushoj-admin-bootstrap` Job，不会删除用户或数据库数据。

不要丢失本地密码文件：Job 重放不会轮换首个管理员密码。如果文件遗失，应使用正常的密码找回/轮换流程；重新生成 bootstrap Secret 不会、也不应绕过这一限制。

生产环境不要使用本地生成的身份。管理员应先在私有 Secret 管理系统生成唯一用户名、邮箱和至少 12 字符的强密码，再创建同名三键 Secret：

```bash
kubectl create secret generic coderushoj-admin-bootstrap-secret \
  --namespace coderushoj \
  --from-file=username=/secure/path/username \
  --from-file=email=/secure/path/email \
  --from-file=password=/secure/path/password

helm template coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --values /secure/path/production-values.yaml \
  --set applications.enabled=true \
  --set bootstrapAdmin.enabled=true \
  --show-only templates/admin-bootstrap-job.yaml \
  | kubectl apply --filename -
kubectl wait -n coderushoj --for=condition=complete \
  job/coderushoj-admin-bootstrap --timeout=6m
```

生产镜像仍由 values 中的 digest 固定。成功后删除 Job Secret，并通过正常的认证接口轮换密码；不要把初始密码写进 values、Issue、命令行参数或 Git。

部署会完成：

1. 创建 1 个控制平面和 2 个同时带 `coderushoj.io/judge-worker=true`、`coderushoj.io/sandbox=true` 标签的工作节点；
2. 安装校验和固定的 Envoy Gateway v1.8.2 清单；
3. 生成 Kubernetes Secret，但不在终端打印值；
4. 安装 MySQL、Redis、RocketMQ、SeaweedFS 和仅限本地验收的 Mailpit 邮件捕获器；
5. 创建 `submission-topic` 与 `submission-dead-letter-topic`；
6. 在显式启用应用 profile 后，安装前端、后端、文档、异步 REST 判题服务和两个长期运行的沙箱副本；
7. 创建 `sandbox-workers` headless Service，由判题服务通过 Service DNS 和 gRPC `round_robin` 使用 EndpointSlice；
8. 安装 `coderushoj.local`、`docs.coderushoj.local` 路由；Kind profile 额外开放 `judge.coderushoj.local/api/v1`；
9. 验证 SQL、缓存、消息主题、S3 读写、工作负载探针和 Gateway 状态。

查看状态：

```bash
kubectl get nodes -L coderushoj.io/judge-worker,coderushoj.io/sandbox
kubectl get pods,pvc -n coderushoj
kubectl get service sandbox-workers -n coderushoj
kubectl get endpointslice -n coderushoj -l kubernetes.io/service-name=sandbox-workers
kubectl get gateway,httproute -n coderushoj
helm list -n coderushoj
```

本地入口使用 `Host` 头：

```bash
curl -H 'Host: coderushoj.local' http://127.0.0.1:8080/
curl -H 'Host: docs.coderushoj.local' http://127.0.0.1:8080/
read -r -s CROJ_EXTERNAL_API_KEY
curl -H 'Host: judge.coderushoj.local' \
  -H "Authorization: Bearer $CROJ_EXTERNAL_API_KEY" \
  http://127.0.0.1:8080/api/v1/capabilities
unset CROJ_EXTERNAL_API_KEY
```

外部判题 REST 在默认 values 中只创建 ClusterIP，不对集群外公开；`values-kind.yaml` 仅为本地联调显式开放 HTTP。capabilities 也要求具有 `capabilities:read` scope 的 Bearer API key，不能匿名调用。租户和 API key 由 `croj-judging-server` 的 `judge-admin` 创建，secret 只显示一次。生产环境必须预先创建覆盖主站/文档域名的 `coderushoj-web-tls` Secret，并为 Judge 配置独立 TLS Secret、网络出口策略和 CI 发布的镜像 digest，不能照搬本地 HTTP 配置。

本地注册和邮箱验证码会进入 Mailpit，不会发到公网。需要人工查看时临时转发 UI；结束 `kubectl port-forward` 即可，不需要暴露 Ingress：

```bash
kubectl port-forward -n coderushoj service/coderushoj-infra-mailpit 8025:8025
# 浏览器打开 http://127.0.0.1:8025
```

生产 profile 不部署 Mailpit，并对空的 `backend.smtp.host`/`backend.smtp.username` fail closed。部署者必须在私有 values 中设置真实 SMTP host、port、username、auth/STARTTLS/SSL 模式，并在 `coderushoj-production-secrets` 中提供 `smtp-password`；不要把密码写入 values 或 Git。

沙箱默认依赖专用节点标签而不假设集群存在某个 RuntimeClass。若生产集群已经由管理员安装隔离运行时，可设置 `sandbox.runtimeClassName`；不要填写一个未注册的名字，否则 Pod 会保持 Pending。

本地 Secret 生成器还会创建 JWT、内部判题回调 token、Mailpit/SMTP 密码和四个 32-byte Base64 外部 API 密钥材料。它只显示文件路径，不打印值；已有文件不会被静默轮换。

## 升级

先备份，再渲染检查差异，最后原子升级：

```bash
helm upgrade coderushoj-infra ./charts/coderushoj-infra \
  --namespace coderushoj --rollback-on-failure --wait --timeout 12m
helm upgrade coderushoj ./charts/coderushoj \
  --namespace coderushoj --values ./charts/coderushoj/values-kind.yaml \
  --rollback-on-failure --wait --timeout 5m
make smoke
```

## 回滚

```bash
helm history coderushoj-infra -n coderushoj
helm rollback coderushoj-infra PREVIOUS_REVISION -n coderushoj --wait
helm history coderushoj -n coderushoj
helm rollback coderushoj PREVIOUS_REVISION -n coderushoj --wait
make smoke
```

回滚 Helm 不会自动回滚数据库数据或不可逆 DDL；数据库迁移必须采用向前兼容的 expand/contract 策略。

## 构建多架构镜像

各原仓库的 CI 使用 Buildx 发布 `linux/amd64,linux/arm64` 镜像，开发 values 固定 SemVer 且不使用 `latest`；生产 profile 缺少任意镜像 digest 时 Helm 会直接拒绝渲染：

```bash
docker buildx create --name coderushoj-builder --use
docker buildx build --platform linux/amd64,linux/arm64 \
  --tag ghcr.io/coderushoj/SERVICE:VERSION --push .
```
