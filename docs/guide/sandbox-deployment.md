# Sandbox Kubernetes 部署

`croj-sandbox` 在隔离的 Linux 节点执行不可信代码。当前 Chart 使用两个副本、headless Service、gRPC 健康检查、专用节点标签和最小网络流；它属于完整应用 release，不单独暴露公网端口。

## 服务发现合同

Service 名固定为 `sandbox-workers`，端口是 `50051/TCP`，`clusterIP: None`。Judging 的 `SANDBOX_GRPC_TARGET` 是：

```text
dns:///sandbox-workers:50051
```

集群内实际值带 namespace FQDN。gRPC 使用 `round_robin` 解析 DNS 返回的 Ready endpoint，不需要 ServiceAccount token，也不读取 Kubernetes API。Kubernetes 仍以 EndpointSlice 表示就绪实例；运维应同时检查 Service、EndpointSlice 和 Pod：

```bash
kubectl get service sandbox-workers -n coderushoj
kubectl get endpointslice -n coderushoj \
  -l kubernetes.io/service-name=sandbox-workers -o wide
kubectl get pods -n coderushoj \
  -l app.kubernetes.io/component=sandbox -o wide
```

每个 Pod 通过 Downward API 获得唯一 `CROJ_SANDBOX_INSTANCE_ID`。Startup、readiness 和 liveness 都使用原生 gRPC probe；只有真正 Ready 的 endpoint 才会进入判题流量。

产品 E2E 进一步要求至少两个 Ready EndpointSlice endpoint，且分布到两个带 `coderushoj.io/sandbox=true` 标签的 worker node。这是多副本调度和 Kubernetes 服务发现的运行证据，不是只检查 YAML。

## 节点与权限边界

Sandbox Pod 使用：

- `nodeSelector: coderushoj.io/sandbox=true`；
- `hostPID: true`；
- privileged 容器；
- 只读根文件系统与 `/tmp` 限额；
- `/usr/bin/nsenter --cgroup=/proc/1/ns/cgroup -- /app/api-server`；
- 宿主 `/sys/fs/cgroup` 只按执行器所需方式挂载；
- `automountServiceAccountToken: false`。

这些权限用于让执行器在节点 cgroup v2 层级实施资源和进程限制。privileged、hostPID 与 nsenter 都扩大节点影响面，因此 sandbox 节点必须是隔离、可重建、无控制平面和无业务 Secret 的专用 worker。不要把 sandbox 调度到共享数据库节点或互联网可达的普通应用节点。

Sandbox 镜像本身还必须对 cgroup、进程组、输出、超时、文件系统和语言工具链失败关闭；平台 Chart 的权限设置不能替代执行器仓库的安全测试与镜像扫描。

## Kind 验收

专用三节点配置在 `config/kind/product-e2e.yaml` 中给两个 worker 都设置 sandbox 标签。先构建并载入锁定镜像，再使用 `values-kind-app.yaml`：

```bash
make source-verify
make source-checkout
make images-build
make images-load

helm upgrade --install coderushoj charts/coderushoj \
  --namespace coderushoj \
  --values charts/coderushoj/values-kind.yaml \
  --values charts/coderushoj/values-kind-app.yaml \
  --rollback-on-failure --wait --timeout 15m
```

`sandbox.replicas` 默认是两个，`sandbox.maxConcurrency=2` 会传给 API server 的 `-max-concurrency`。不要把 concurrency 调得大于节点经过真实编译/运行压测证明的容量。

## NetworkPolicy

专用产品 E2E 禁用 kindnet 并安装版本和清单 checksum 都固定的 Calico。应用默认拒绝策略只允许 Judging Pod 访问 `sandbox-workers:50051`，Sandbox 没有业务出口。验收必须同时包含：

- Judging 经 headless Service 完成真实多 case 判题的正向路径；
- 未授权 Pod 连接 `sandbox-workers:50051` 超时的负向路径；
- Calico `tigerastatus/calico` 为 Available；
- 两个 Ready endpoint 分布到两个 worker。

普通 Kind `config/kind/cluster.yaml` 仍用于基础设施 smoke；不要把仅创建 NetworkPolicy 对象误称为已经执行隔离。完整策略门禁见[三节点产品 E2E](../operations/product-e2e.md)。

## 生产镜像与发布

`values-production.yaml` 启用完整应用并强制五个镜像使用 digest。Sandbox 必须设置 `images.sandbox.digest`；可变 tag、短摘要或大写摘要都会被 schema 拒绝。

先检查专用节点：

```bash
kubectl get nodes -l coderushoj.io/sandbox=true
kubectl get runtimeclass
```

如果平台使用经过验证的 RuntimeClass，可通过 `sandbox.runtimeClassName` 显式设置；不要猜测或在缺少运行时的集群中填写。离线渲染：

```bash
helm template coderushoj charts/coderushoj \
  --namespace coderushoj \
  --values charts/coderushoj/values-production.yaml \
  --values application-production-values.yaml \
  | kubeconform -strict -summary -ignore-missing-schemas
```

生产上线前必须复现真实 C++ 编译、至少两个 case、超时/内存/输出限制、Pod 重启、节点故障、滚动升级和 NetworkPolicy 正反向探针。任何隔离自检失败、没有两个可用 worker、RuntimeClass 不可用或 EndpointSlice 只有一个 Ready endpoint，都应阻止发布。

## 容量、升级与回滚

默认每个 Pod 请求 `500m CPU / 768Mi`，限制 `2 CPU / 2Gi`，`/tmp` 使用限额 `4Gi` 的 `emptyDir`。容量评估必须包含编译峰值和并发运行，而不只是空闲 RSS。

滚动升级前确认两个 endpoint 分布在两个 worker；升级期间持续观察：

```bash
kubectl rollout status deployment/croj-sandbox -n coderushoj --timeout=5m
kubectl get endpointslice -n coderushoj \
  -l kubernetes.io/service-name=sandbox-workers -w
```

回滚使用整个应用 release：

```bash
helm history coderushoj -n coderushoj
helm rollback coderushoj PREVIOUS_REVISION -n coderushoj --wait
```

回滚后重新运行真实判题和 EndpointSlice 分布检查；不要只以 Deployment Available 作为恢复完成。
