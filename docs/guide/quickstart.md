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

Kind/Helm 路径要求 Linux cgroup v2；macOS 通过 Colima VM 提供 Linux 内核。平台底座部署不会默认启动 sandbox。要运行不可信代码，还需要构建 `croj-sandbox` 镜像，并按 [Sandbox Kubernetes 部署](./sandbox-deployment.md) 选择本地开发或生产隔离 profile。

一条完整的本地部署链路：

```bash
make bootstrap
make cluster-up
make deploy
make smoke
```

部署会完成：

1. 创建 1 个控制平面和 2 个带 `coderushoj.io/judge-worker=true` 标签的工作节点；
2. 安装校验和固定的 Envoy Gateway v1.8.2 清单；
3. 生成 Kubernetes Secret，但不在终端打印值；
4. 安装 MySQL、Redis、RocketMQ 和 SeaweedFS；
5. 创建 `submission-topic` 与 `submission-dead-letter-topic`；
6. 安装 `coderushoj.local` 的 `/`、`/api`、`/docs` 路由；
7. 验证 SQL、缓存、消息主题、S3 读写和 Gateway 状态。

应用 Chart 中的 sandbox 默认为 `sandbox.enabled=false`。这是镜像接入期间的安全门禁，不影响基础设施与 Gateway 冒烟测试，也避免安装平台时意外获得节点级权限。

查看状态：

```bash
kubectl get nodes -L coderushoj.io/judge-worker
kubectl get pods,pvc -n coderushoj
kubectl get gateway,httproute -n coderushoj
helm list -n coderushoj
```

需要验证 sandbox 清单但不启动服务时：

```bash
helm template coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --values ./charts/coderushoj/values-kind.yaml \
  --set sandbox.enabled=true \
  | kubeconform -strict -summary -ignore-missing-schemas
```

本地入口使用 `Host` 头：

```bash
curl -H 'Host: coderushoj.local' http://127.0.0.1:8080/
```

在应用镜像接入前，入口返回后端引用不存在属于阶段性预期；Gateway 本身必须为 `Programmed=True`。

## 升级

先备份，再渲染检查差异，最后原子升级。`scripts/deploy.sh` 会自动为 Helm 3 选择 `--atomic`、为 Helm 4 选择 `--rollback-on-failure`；手动执行时使用同一判断：

```bash
case "$(helm version --template '{{.Version}}')" in
  v3.*) coderushoj_rollback_flag=--atomic ;;
  v4.*) coderushoj_rollback_flag=--rollback-on-failure ;;
  *) echo "unsupported Helm version" >&2; exit 1 ;;
esac

helm upgrade coderushoj-infra ./charts/coderushoj-infra \
  --namespace coderushoj "$coderushoj_rollback_flag" --wait --timeout 12m
helm upgrade coderushoj ./charts/coderushoj \
  --namespace coderushoj --values ./charts/coderushoj/values-kind.yaml \
  "$coderushoj_rollback_flag" --wait --timeout 5m
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

各原仓库的 CI 最终使用 Buildx 发布 `linux/amd64,linux/arm64` 镜像，部署清单固定 SemVer 或 digest，不使用 `latest`：

```bash
docker buildx create --name coderushoj-builder --use
docker buildx build --platform linux/amd64,linux/arm64 \
  --tag ghcr.io/coderushoj/SERVICE:VERSION --push .
```
