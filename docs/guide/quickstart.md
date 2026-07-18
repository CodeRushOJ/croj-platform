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

部署会完成：

1. 创建 1 个控制平面和 2 个带 `coderushoj.io/judge-worker=true` 标签的工作节点；
2. 安装校验和固定的 Envoy Gateway v1.8.2 清单；
3. 生成 Kubernetes Secret，但不在终端打印值；
4. 安装 MySQL、Redis、RocketMQ 和 SeaweedFS；
5. 创建 `submission-topic` 与 `submission-dead-letter-topic`；
6. 安装 `coderushoj.local` 的 `/`、`/api`、`/docs` 路由；
7. 验证 SQL、缓存、消息主题、S3 读写和 Gateway 状态。

查看状态：

```bash
kubectl get nodes -L coderushoj.io/judge-worker
kubectl get pods,pvc -n coderushoj
kubectl get gateway,httproute -n coderushoj
helm list -n coderushoj
```

本地入口使用 `Host` 头：

```bash
curl -H 'Host: coderushoj.local' http://127.0.0.1:8080/
```

在应用镜像接入前，入口返回后端引用不存在属于阶段性预期；Gateway 本身必须为 `Programmed=True`。

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

各原仓库的 CI 最终使用 Buildx 发布 `linux/amd64,linux/arm64` 镜像，部署清单固定 SemVer 或 digest，不使用 `latest`：

```bash
docker buildx create --name coderushoj-builder --use
docker buildx build --platform linux/amd64,linux/arm64 \
  --tag ghcr.io/coderushoj/SERVICE:VERSION --push .
```
