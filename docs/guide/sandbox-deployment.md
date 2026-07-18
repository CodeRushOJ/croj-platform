# Sandbox Kubernetes 部署

`croj-sandbox` 是运行不可信用户代码的 gRPC 服务。应用 Chart 已提供 Deployment、ClusterIP Service、原生 gRPC 探针、网络隔离和专用节点调度；在镜像完成验证前默认不启动，必须显式设置 `sandbox.enabled=true`。

## 发现契约

判题编排器通过 Kubernetes API 读取 `coderushoj` namespace 中属于 `croj-sandbox` Service 的 EndpointSlice：

| 字段 | 固定契约 |
| --- | --- |
| Service | `croj-sandbox` |
| 端口名 | `grpc` |
| 端口 | `50051/TCP` |
| 可调度条件 | Endpoint `Ready=true` 且 `Terminating!=true` |
| 实例标识 | Downward API 将 Pod UID 注入 `CROJ_SANDBOX_INSTANCE_ID` |

Service selector 与 Pod label 都是 `app.kubernetes.io/name=croj-sandbox` 和当前 Helm release 的 `app.kubernetes.io/instance`。只允许带 `app.kubernetes.io/name=croj-judging-server` 的 Pod 访问 gRPC 端口，sandbox 默认没有网络出口，也不挂载 ServiceAccount token。

Chart 同时创建 `coderushoj-judging-server` ServiceAccount 与 namespace 级 Role/RoleBinding；唯一权限是对 `discovery.k8s.io/endpointslices` 执行 `list`，没有 Secret、Pod、Node 或集群级权限。judging-server Deployment 必须显式使用该 ServiceAccount。

启动、就绪和存活探针都调用标准 gRPC Health Checking Protocol 的空服务名。sandbox 只有在语言工具链、临时目录与 cgroup 自检通过后才报告 `SERVING`，因此 EndpointSlice 不会把尚不能执行代码的 Pod 交给 judging-server。

## 本地 Kind 开发 profile

本机先完成通用 [安装前置条件](./quickstart.md)，并确保 Colima/Docker VM 使用 Linux cgroup v2。参考 Kind 集群已把两个 worker 标记为 `coderushoj.io/judge-worker=true`。

在 `croj-sandbox` 仓库构建镜像并导入 Kind；这只构建和导入镜像，不会启动容器：

```bash
docker buildx build --load --tag ghcr.io/coderushoj/croj-sandbox:dev \
  ../croj-sandbox
kind load docker-image ghcr.io/coderushoj/croj-sandbox:dev --name coderushoj
```

先离线渲染检查，再显式启用：

```bash
helm template coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --values ./charts/coderushoj/values-kind.yaml \
  --set sandbox.enabled=true \
  --set sandbox.image.tag=dev

helm upgrade --install coderushoj ./charts/coderushoj \
  --namespace coderushoj --create-namespace \
  --values ./charts/coderushoj/values-kind.yaml \
  --set sandbox.enabled=true \
  --set sandbox.image.tag=dev \
  --rollback-on-failure --wait --timeout 5m
```

`values-kind.yaml` 是明确的开发例外：Pod 调度到 `coderushoj.io/judge-worker=true` 节点，使用 `privileged: true`，并以 `Bidirectional` 方式读写挂载宿主机 `/sys/fs/cgroup`。这是为了兼容当前 cgroup 管理实现，只适用于受控的本地 Kind VM；它扩大了容器逃逸和节点破坏的影响面，禁止复制到互联网可达或多租户集群。

检查 Service/EndpointSlice 契约：

```bash
kubectl get deploy,svc,endpointslice -n coderushoj \
  -l app.kubernetes.io/name=croj-sandbox
kubectl get pods -n coderushoj -l app.kubernetes.io/name=croj-sandbox -o wide
kubectl describe pod -n coderushoj -l app.kubernetes.io/name=croj-sandbox
```

## Production 参考 profile

生产环境不要授予无限制的 `privileged` 或挂载宿主机 cgroup。`values-production.yaml` 采用下列 fail-closed 边界：

- 只调度到 `coderushoj.io/sandbox-worker=true` 的隔离节点池；
- 要求预先安装并验证名为 `kata-qemu` 的 RuntimeClass；
- 非 root UID/GID `65532`、只读根文件系统、删除所有 capabilities、禁止提权；
- 不挂载宿主机 cgroup，不提供 Kubernetes API 凭据，默认拒绝网络出口；
- 强制 `sandbox.image.digest`，拒绝只用可变 tag 的安装。

安装前必须完成独立节点池、RuntimeClass、内核/cgroup 委派、镜像签名和对抗性用例验证。若环境没有 `kata-qemu`，Pod 保持 Pending 是预期的安全失败，不应通过改回 privileged 来绕过。

```bash
kubectl label node SANDBOX_NODE coderushoj.io/sandbox-worker=true
kubectl get runtimeclass kata-qemu

helm template coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --values ./charts/coderushoj/values-production.yaml \
  --set-string sandbox.image.digest=sha256:IMAGE_DIGEST

helm upgrade --install coderushoj ./charts/coderushoj \
  --namespace coderushoj --create-namespace \
  --values ./charts/coderushoj/values-production.yaml \
  --set-string sandbox.image.digest=sha256:IMAGE_DIGEST \
  --rollback-on-failure --wait --timeout 10m
```

`IMAGE_DIGEST` 必须替换为 registry 返回的 64 位 sha256。生产上线门禁还包括 `croj-sandbox` 仓库中的 cgroup、seccomp、网络、fork bomb、TLE/MLE/OLE 和文件系统逃逸测试；仅通过 Helm schema 不代表执行器已经完成生产安全认证。

## 容量与升级

默认 2 个副本，每个副本请求 `500m CPU / 512Mi`、限制 `2 CPU / 2Gi`，临时目录使用限额 `4Gi` 的 `emptyDir`。根据并行执行模型和节点压力调整 `sandbox.replicaCount` 与 `sandbox.resources`，不要用无限资源换取吞吐量。

滚动升级时，Pod 在接收终止信号后先把 gRPC health 改为 `NOT_SERVING`，Kubernetes 随即从 EndpointSlice Ready 集合移除该实例，再等待连接优雅结束。升级前先用 `helm template` 与 kubeconform 验证清单，并确认 judging-server 的 namespace、Service 名和端口名没有被覆盖。
