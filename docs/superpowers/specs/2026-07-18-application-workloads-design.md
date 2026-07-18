# CodeRushOJ Application Workloads Design

## Scope

This change adds opt-in Helm workloads for `croj-backend`, `croj-frontend`, and
`croj-judging-server`. It does not install or start them during development.
The existing Gateway routes remain authoritative: `/api` targets
`croj-backend:7999`, while `/` targets `croj-frontend:80`. The judging server
is cluster-internal and therefore has no Service.

## Chart structure

Each application gets an explicit template so that its ports, probes,
environment, and security contract remain reviewable. `_helpers.tpl` owns only
shared image-reference and label helpers; a generic workload loop is avoided
because it would make schema errors and component-specific security choices
opaque.

All three workloads are disabled by default. Enabling one renders its
Deployment, an optional PDB, and its topology-spread rules. Backend and frontend
also render fixed-name ClusterIP Services. Judging uses the existing
`coderushoj-judging-server` ServiceAccount and namespace-scoped, list-only
EndpointSlice Role.

## Images and production fail-closed behavior

Every image accepts `repository`, `tag`, `digest`, `requireDigest`, and
`pullPolicy`. A digest, when present, wins over the tag. The production profile
sets `requireDigest: true` for every application and sandbox image. Enabling a
production workload without a valid `sha256:` digest fails during Helm render.
Default application values stay disabled so an incomplete production stack is
never started accidentally.

## Configuration and Secret contract

Non-secret connection metadata stays in values: database/Redis/RocketMQ hosts
and ports, versioned MQ topic/group names, callback timeout, and EndpointSlice
discovery configuration. Credentials are read only from a user-created Secret.
Templates and values contain no credential value.

Backend and judging each declare `existingSecret.name` plus explicit key names.
When either secret-consuming workload is enabled, Helm fails if the Secret name
or any required key mapping is empty. Both components default the judge callback
token mapping to the same key, `JUDGE_RESULT_SERVICE_TOKEN`. Helm does not use
`lookup`, preserving deterministic offline rendering. A strict preflight script
checks that the referenced Secret exists and contains every required key before
an install.

Backend receives database credentials, Redis password, JWT secret, SMTP
credentials, and the judge result service token. Judging receives database
credentials and the same judge result service token. Public configuration is
injected explicitly; judging uses `BACKEND_INTERNAL_URL=http://croj-backend:7999/api`,
the fixed sandbox Service/port name, a versioned submission topic and consumer
group, and a bounded callback timeout.

## Runtime safety and availability

Application Pods run as non-root, disallow privilege escalation, drop all Linux
capabilities, use `RuntimeDefault` seccomp, and use a read-only root filesystem.
Writable locations are explicit `emptyDir` volumes where each image needs them.
Probes target native HTTP health endpoints for backend/frontend and process/TCP
health compatible with the judging image. Resource requests and limits are
required in values. PDB and topology-spread/anti-affinity defaults reduce
single-node correlated failure without making one-node development rendering
unschedulable.

Sandbox `maxConcurrency` becomes a typed value passed to `api-server`; the
default of two matches the two-CPU limit. Documentation requires keeping it at
or below the whole-CPU execution budget.

## Network policy

Application NetworkPolicies are an explicit opt-in. Policy templates describe
the intended backend/frontend/judging/sandbox flows, but the local Kind profile
keeps enforcement disabled because kindnet does not implement NetworkPolicy.
Documentation and preflight output must never claim isolation unless a
policy-capable CNI has been installed and tested.

## Validation

Contract tests render each enabled workload, verify fixed Services, RBAC,
probes, security contexts, Secret references, MQ/discovery/callback values,
PDB/topology rules, and sandbox concurrency. Negative tests prove missing Secret
references and missing production digests fail. The preflight script is tested
with a fake `kubectl`. CI runs unit contracts, Helm lint, kubeconform for default,
development, and production render profiles, and the documentation build.

