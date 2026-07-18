# Sandbox Kubernetes 部署

`croj-sandbox` 是运行不可信用户代码的 gRPC 服务。应用 Chart 已提供 Deployment、ClusterIP Service、原生 gRPC 探针、NetworkPolicy 声明和专用节点调度；开发与 production values 均默认 `sandbox.enabled=false`，不会随平台底座启动。

## 发现契约

判题编排器通过 Kubernetes API 读取 `coderushoj` namespace 中属于 `croj-sandbox` Service 的 EndpointSlice：

| 字段 | 固定契约 |
| --- | --- |
| Service | `croj-sandbox` |
| 端口名 | `grpc` |
| 端口 | `50051/TCP` |
| 可调度条件 | Endpoint `Ready=true` 且 `Terminating!=true` |
| 实例标识 | Downward API 将 Pod UID 注入 `CROJ_SANDBOX_INSTANCE_ID` |

Service 名固定为 `croj-sandbox`，不能通过 values 改名；selector 与 Pod label 固定包含 `app.kubernetes.io/name=croj-sandbox` 和当前 Helm release 的 `app.kubernetes.io/instance`，`podLabels` 不能覆盖这两个保留键。设置 `sandbox.networkPolicy.enabled=true` 才会渲染只允许 `croj-judging-server` 访问 gRPC 且禁止 sandbox 出网的策略；只有支持并启用 NetworkPolicy 的 CNI 才会执行这些规则。sandbox 不挂载 ServiceAccount token。

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

case "$(helm version --template '{{.Version}}')" in
  v3.*) sandbox_rollback_flag=--atomic ;;
  v4.*) sandbox_rollback_flag=--rollback-on-failure ;;
  *) echo "unsupported Helm version" >&2; exit 1 ;;
esac

helm upgrade --install coderushoj ./charts/coderushoj \
  --namespace coderushoj --create-namespace \
  --values ./charts/coderushoj/values-kind.yaml \
  --set sandbox.enabled=true \
  --set sandbox.image.tag=dev \
  "$sandbox_rollback_flag" --wait --timeout 5m
```

`values-kind.yaml` 是明确的开发例外：Pod 调度到 `coderushoj.io/judge-worker=true` 节点，设置 `hostPID: true` 和 `privileged: true`，并以 `Bidirectional` 方式读写挂载宿主机 `/sys/fs/cgroup`。容器通过 `/usr/bin/nsenter --cgroup=/proc/1/ns/cgroup -- /app/api-server` 进入节点 PID 1 的 cgroup namespace，才能让当前执行器的启动自检与限制路径作用在节点 cgroup v2 层级。

这些权限只适用于受控的本地 Kind VM；它们让容器看见宿主进程并能修改节点 cgroup，显著扩大容器逃逸和节点破坏的影响面，禁止复制到互联网可达或多租户集群。

::: danger Kind 网络策略不生效
参考集群当前使用 Kind 默认 kindnet；kindnet 不执行 NetworkPolicy。Chart 会创建策略对象，但本地 Kind 不能据此宣称已阻断 sandbox 网络。上线强制执行和正反向网络探针由 [Issue #4](https://github.com/CodeRushOJ/croj-platform/issues/4) 跟踪。在切换到经过验证的 policy-capable CNI 前，只能在无外部凭据、无生产网络可达性的隔离开发机上测试。
:::

检查 Service/EndpointSlice 契约：

```bash
kubectl get deploy,svc,endpointslice -n coderushoj \
  -l app.kubernetes.io/name=croj-sandbox
kubectl get pods -n coderushoj -l app.kubernetes.io/name=croj-sandbox -o wide
kubectl describe pod -n coderushoj -l app.kubernetes.io/name=croj-sandbox
```

## Production 参考 profile

`values-production.yaml` 是默认禁用的 fail-closed 参考清单，不是可运行或已认证的生产部署。当前执行器存在以下阻塞项：

- 受评测 child 已经 `Start()` 后才调用安全设置，seccomp 不能可靠约束已启动 child，且隔离失败路径仍可能记录告警后继续；
- gRPC 控制进程与用户编译/执行进程仍在同一容器身份与信任域；
- 非 root Kata profile 没有定义或验证可写的 delegated cgroup，当前启动自检会保持 `NOT_SERVING`；
- 尚未完成 production RuntimeClass、cgroup、seccomp、fork bomb、网络和文件系统逃逸的 live acceptance。

因此 production values 保持 `sandbox.enabled=false`。在执行器改为 exec 前不可降级地应用身份/seccomp、任何隔离失败 fail closed，并完成可写 cgroup 委派与 live 验收之前，不得通过 `--set sandbox.enabled=true` 部署生产流量。

目标 production 边界是：

- 只调度到 `coderushoj.io/sandbox-worker=true` 的隔离节点池；
- 要求预先安装并验证名为 `kata-qemu` 的 RuntimeClass；
- 非 root UID/GID `65532`、只读根文件系统、删除所有 capabilities、禁止提权；
- 不挂载宿主机 cgroup，不提供 Kubernetes API 凭据，默认拒绝网络出口；
- 强制 `sandbox.image.digest`，拒绝只用可变 tag 的安装。

若环境没有 `kata-qemu` 或明确的 cgroup 委派，不能通过改回 privileged 来绕过。以下命令仅渲染未来清单用于 schema 和审查，不会安装资源：

```bash
kubectl label node SANDBOX_NODE coderushoj.io/sandbox-worker=true
kubectl get runtimeclass kata-qemu

helm template coderushoj ./charts/coderushoj \
  --namespace coderushoj \
  --values ./charts/coderushoj/values-production.yaml \
  --set sandbox.enabled=true \
  --set-string sandbox.image.digest=sha256:IMAGE_DIGEST
```

`IMAGE_DIGEST` 必须替换为 registry 返回的 `sha256:` 加 64 位小写十六进制摘要；placeholder、短值、非 sha256 或大写摘要都会被 schema 与模板拒绝。仅通过 Helm schema 不代表执行器已经完成生产安全认证。

## 容量与升级

默认 2 个副本，每个副本请求 `500m CPU / 512Mi`、限制 `2 CPU / 2Gi`，临时目录使用限额 `4Gi` 的 `emptyDir`。`sandbox.maxConcurrency=2` 会传给 api-server 的 `-max-concurrency` 参数，与默认 2 CPU limit 对齐；调小时可降低单 Pod 压力，调大前必须用真实编译/执行负载证明 CPU、内存与临时盘仍有界。根据并行执行模型和节点压力调整 `sandbox.replicaCount` 与 `sandbox.resources`，不要用无限资源换取吞吐量。

目标滚动升级行为是 Pod 在接收终止信号后先把 gRPC health 改为 `NOT_SERVING`，Kubernetes从 EndpointSlice Ready 集合移除该实例，再等待连接优雅结束。当前尚未完成真实 judging-server → sandbox gRPC 判题与重试的端到端验收，不能据此承诺执行中的提交一定无损恢复。
