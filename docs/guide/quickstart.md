# 安装与部署

CodeRushOJ 提供两条路径：Docker Compose 用于单机开发和快速体验；三节点 Kind + Helm 用于验证生产形态、Kubernetes 调度和判题沙箱。用户不需要在宿主机安装 Node、MySQL、Redis 或 RocketMQ；宿主 Go 是可选工具，OpenJDK 17 同样只用于本机开发检查。

## 前置条件

macOS 推荐 Colima；Linux 可直接使用 Docker Engine。仓库的 `Brewfile` 固定了本地工具清单。

```bash
brew bundle --file Brewfile
colima start --cpu 6 --memory 8 --disk 50 --arch aarch64 --vm-type vz
```

`brew bundle` 会安装 Go，供本机执行 Go 静态检查和 `go install` 类工具安装。若开发者只使用容器化命令，可以不单独准备宿主 Go，Docker Compose 路径仍可用，镜像构建也继续在 Docker/Buildx 中完成。

OpenJDK 17 是可选工具，只在进入 Backend checkout 执行本机 Maven 测试（例如 `./mvnw test`）时需要。Homebrew 的 `openjdk@17` 是 keg-only formula；在运行测试的 shell 中显式设置路径，避免误用其他 Java 版本：

```bash
export PATH="$(brew --prefix openjdk@17)/bin:$PATH"
export JAVA_HOME="$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home"
java -version
```

只使用 Compose、Kind、Docker/Buildx 构建和容器内测试时不需要这些环境变量，也不要求宿主 JDK 可用。

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

基础命令不会尝试拉取尚未发布的应用镜像。开发者从不可变源码锁构建四个外部组件镜像，并从当前平台 checkout 构建 Docs 镜像；把这五个本地镜像载入 Kind 后，再显式启用应用 profile：

```bash
make source-verify
make source-checkout
make images-build
make images-load
helm upgrade --install coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --values ./charts/coderushoj/values-kind.yaml \
  --values ./charts/coderushoj/values-kind-app.yaml \
  --rollback-on-failure --wait --timeout 10m
```

`values-kind-app.yaml` 使用 `imagePullPolicy: Never`，任何未加载镜像都会立即暴露为部署错误，不会悄悄从不可信标签拉取。跨仓库集成 CI 会在发布前替代这段人工加载流程。

### 不可变源码与开发镜像

`config/source-lock.json` 固定 frontend、backend、judging-server 和 sandbox 四个外部仓库的 40 位 commit、Dockerfile、构建上下文及精确 `:dev` 镜像名。校验器拒绝 branch/tag、外部仓库、路径穿越、未知字段、缺失组件和重复镜像。Docs 不进入源码锁，也不会从旧平台提交构建；`images-build` 直接使用当前平台 checkout，并用当前 `GITHUB_SHA`（本地为 `HEAD`）标记 Docs 镜像。平台 checkout 必须完全干净，包括 tracked、staged 和 untracked 文件；若工作树不干净，或环境中的 `GITHUB_SHA` 与 checkout 的 `HEAD` 不同，构建和加载都会 fail closed，避免给未提交内容写入错误 provenance。release workflow 仍从已签名 tag 的当前 tree 构建正式文档镜像。

```bash
make source-verify
./scripts/verify-source-lock.py rows
```

checkout 只把锁定 commit 写入 `.workspace/sources/<组件>/<commit>/`，并保持 detached HEAD。已有目录必须同时满足 commit 一致、工作树干净和 Dockerfile 存在，否则脚本失败且不会执行 `reset` 或 `clean`：

```bash
make source-checkout
# 可为 CI 使用独立缓存目录
CODERUSHOJ_SOURCES_DIR=/absolute/cache/path make source-checkout
```

并发 checkout 使用由独立 helper 持有的内核文件锁；shell 被终止或崩溃后锁会由内核自动释放。升级自旧版本时，遗留的 owner 目录会经过宽限期、双重快照和原子 quarantine 后再清理。默认等待 300 秒、轮询 50 毫秒、遗留目录宽限 1000 毫秒；CI 如需更短的失败反馈，可分别设置 `CODERUSHOJ_CHECKOUT_LOCK_TIMEOUT_MS`、`CODERUSHOJ_CHECKOUT_LOCK_POLL_MS`、`CODERUSHOJ_CHECKOUT_LOCK_LEGACY_GRACE_MS`，三者必须为正整数且宽限期不能短于轮询间隔。

隐藏测试数据协议必须通过真实 producer-to-consumer 门禁。下面的命令让锁定 Backend 运行正式导入代码并导出 TestBundle v1 ZIP，再把该文件的绝对路径交给锁定 Judging 测试；任何一端缺少契约入口、产物为空或判题侧拒绝都会失败：

```bash
make test-bundle-contract
```

构建会自动执行上述校验和 checkout，随后逐个调用 `docker buildx build --load`。四个外部组件把锁定仓库与 commit 写入 OCI `source`/`revision` 标签，Docs 则写入平台官方仓库与当前 checkout revision：

```bash
make images-build
docker image inspect ghcr.io/coderushoj/croj-judging-server:dev \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
```

加载是独立的显式步骤，只接受已经存在于本机 Docker 的五个镜像。四个外部组件的 OCI `source`、`revision` 必须与源码锁完全一致，Docs 必须与当前平台 checkout 一致。标签缺失或失配时会在调用 Kind 前失败；它不会创建或启动集群，集群不存在时也会直接失败：

```bash
make images-load
CODERUSHOJ_CLUSTER_NAME=my-cluster make images-load
```

任一组件（包括后端和判题服务）的最终集成提交准备好后，只把对应 `commit` 更新为经评审且可从官方仓库 fetch 的 40 位对象 ID，然后依次运行 `make source-verify`、`make source-checkout`、`make test-bundle-contract`、`make images-build`。锁文件的 PR diff 是版本变更的审计记录；不要增加 branch 字段，也不要用可变 tag 替代 commit。该契约门禁只证明隐藏测试包兼容，完整业务闭环仍必须通过 Kind 端到端验收。

CI 的 `platform-product-e2e` job 会构建上述四个锁定组件镜像和当前 workflow checkout 的 Docs 镜像，在自己命名的三节点 disposable Kind 集群中运行登录、FPS 导入、TestBundle、产品提交、外部异步判题、公告、题目讨论、题解、比赛、邮件和 NetworkPolicy 的真实闭环。完整信任边界、一次性管理员 bootstrap 和安全清理规则见[三节点产品 E2E](../operations/product-e2e.md)。

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

Envoy Gateway controller 与 CRD 不属于两个应用 Helm release。`scripts/install-gateway.sh` 在应用 Chart 之前下载、校验并 server-side apply 固定版本的上游清单；应用 Chart 只管理 GatewayClass、Gateway、HTTPRoute 和 EnvoyProxy 等实例。升级 controller/CRD 必须作为独立平台变更：先审查 `config/versions.env` 中版本与校验和，备份现有 Gateway API 资源，运行安装脚本，确认 controller Available 和 CRD `storedVersions` 兼容，再升级应用 Chart。

```bash
scripts/install-gateway.sh
kubectl get deployment -n envoy-gateway-system envoy-gateway
kubectl get crd | grep -E 'gateway.networking.k8s.io|gateway.envoyproxy.io'
```

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

应用与基础设施是两个独立 Helm release。修改 `judgingServer.externalAPI.enabled` 时，必须在同一次部署变更中把 infra Chart 的 `applications.judgingExternalAPIEnabled` 设为相同布尔值：关闭后不再渲染 Judge→Redis egress 或 Redis→Judge ingress；只有同时启用并设置 `judgingServer.externalAPI.expose=true` 时才开放 Envoy Gateway 到 Judge `8081/TCP`。跨 release 操作遵循以下安全顺序：

- 启用顺序：infra → application。先允许 Redis→Judge，再启动使用 Redis 的 external API worker。
- 禁用顺序：application → infra。先停止 worker/入口，再撤销 Redis ingress。
- 启用失败回滚：application → infra。先回退可能已启动的应用，再撤销预置 infra policy。
- 禁用失败回滚：infra → application。先恢复 Redis ingress，再重新启用应用，避免 Judge 先恢复却无 Redis 通路。

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

回滚应用 Chart 不会回滚 Envoy Gateway controller 或 CRD，也不会自动回滚数据库数据或不可逆 DDL；数据库迁移必须采用向前兼容的 expand/contract 策略。controller 回退需要单独评审目标清单与 CRD stored-version 兼容性，再 apply 先前固定且校验过的清单。不得在普通应用回滚中删除 Gateway API 或 Envoy Gateway CRD；删除 CRD 会影响全 cluster 的 Gateway 资源，并可能造成不可恢复的数据丢失。

## 构建多架构镜像

各原仓库的 CI 使用 Buildx 发布 `linux/amd64,linux/arm64` 镜像，开发 values 固定 SemVer 且不使用 `latest`；生产 profile 缺少任意镜像 digest 时 Helm 会直接拒绝渲染：

```bash
docker buildx create --name coderushoj-builder --use
docker buildx build --platform linux/amd64,linux/arm64 \
  --tag ghcr.io/coderushoj/SERVICE:VERSION --push .
```
