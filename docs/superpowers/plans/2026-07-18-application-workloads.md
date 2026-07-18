# Application Workloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in, production-shaped Helm Deployments for CodeRushOJ backend, frontend, and judging services with external-Secret and Kubernetes-native sandbox discovery contracts.

**Architecture:** Use one explicit template per component plus small shared Helm helpers. Keep all workloads disabled by default, validate external references without cluster `lookup`, and enforce immutable images only in the production profile.

**Tech Stack:** Helm 3/4, Kubernetes apps/v1 and policy/v1 APIs, JSON Schema draft-07, Python unittest render contracts, Bash preflight validation, kubeconform.

---

### Task 1: Render and schema contracts

**Files:**
- Create: `tests/contract/test_application_render.py`
- Modify: `tests/contract/test_sandbox_render.py`
- Modify: `tests/contract/test_scripts.py`

- [ ] **Step 1: Write failing render tests**

Add tests that enable each component with a Secret name and assert its Deployment,
fixed Service contract, image reference, probes, security context, Secret key
references, judging environment, RBAC, PDB, and topology spread. Add negative
tests for missing Secret names, malformed digests, and production mutable images.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.contract.test_application_render tests.contract.test_sandbox_render tests.contract.test_scripts -v`

Expected: failures because the application values, templates, Secret preflight,
and sandbox concurrency argument do not exist.

- [ ] **Step 3: Keep tests behavior-focused**

Assert rendered Kubernetes fields and Helm failure messages; do not duplicate
template implementation or compare complete snapshots.

### Task 2: Values, schema, and helpers

**Files:**
- Create: `charts/coderushoj/templates/_helpers.tpl`
- Modify: `charts/coderushoj/values.yaml`
- Modify: `charts/coderushoj/values-kind.yaml`
- Modify: `charts/coderushoj/values-production.yaml`
- Modify: `charts/coderushoj/values.schema.json`

- [ ] **Step 1: Add typed values**

Define `backend`, `frontend`, and `judgingServer` image, service, resource,
probe, security, PDB, topology, Secret, and public configuration objects. Keep
all application `enabled` flags false.

- [ ] **Step 2: Add fail-closed schema**

Constrain ports, replicas, image digests, pull policies, duration strings,
resource objects, fixed Service names, sandbox max concurrency, and non-empty
Secret key mappings.

- [ ] **Step 3: Add image and label helpers**

Render `repository@digest` when a digest exists, otherwise `repository:tag`;
helpers must fail when `requireDigest=true` and no digest exists.

- [ ] **Step 4: Verify targeted schema tests progress to template failures**

Run the Task 1 unittest command and confirm schema cases pass while workload
render cases still fail.

### Task 3: Backend and frontend workloads

**Files:**
- Create: `charts/coderushoj/templates/backend.yaml`
- Create: `charts/coderushoj/templates/frontend.yaml`

- [ ] **Step 1: Implement backend resources**

Render the fixed `croj-backend:7999` ClusterIP Service, Deployment, probes,
external Secret environment references, writable temp/upload volumes, PDB, and
topology distribution only when enabled.

- [ ] **Step 2: Implement frontend resources**

Render the fixed `croj-frontend:80` Service, non-root HTTP Deployment, probes,
temporary writable volumes, PDB, and topology distribution only when enabled.

- [ ] **Step 3: Verify GREEN for web/API contracts**

Run: `python3 -m unittest tests.contract.test_application_render.ApplicationRenderTest.test_backend_workload tests.contract.test_application_render.ApplicationRenderTest.test_frontend_workload -v`

Expected: both tests pass.

### Task 4: Judging workload and sandbox capacity

**Files:**
- Create: `charts/coderushoj/templates/judging-server.yaml`
- Modify: `charts/coderushoj/templates/judging-server-rbac.yaml`
- Modify: `charts/coderushoj/templates/sandbox.yaml`

- [ ] **Step 1: Implement judging Deployment**

Use the existing ServiceAccount; inject database, versioned MQ, callback,
EndpointSlice discovery, and Secret-backed token variables. Do not create a
Service.

- [ ] **Step 2: Wire sandbox max concurrency**

Append `-max-concurrency=<value>` to the sandbox command arguments without
breaking the Kind `nsenter` command contract.

- [ ] **Step 3: Verify judging, RBAC, and sandbox tests GREEN**

Run the targeted application and sandbox contract modules. Expected: pass.

### Task 5: Secret preflight and opt-in policy

**Files:**
- Create: `scripts/preflight-application-secrets.sh`
- Create: `charts/coderushoj/templates/networkpolicies.yaml`
- Modify: `tests/contract/test_scripts.py`
- Modify: `tests/contract/test_no_secrets.py`

- [ ] **Step 1: Write and observe the preflight test failure**

Use a fake `kubectl` to prove missing Secret and missing key errors are explicit
and no secret values are printed.

- [ ] **Step 2: Implement strict preflight**

Parse only names/key mappings supplied as flags, use `kubectl get secret` to
verify required `.data` keys, and keep `set -Eeuo pipefail`.

- [ ] **Step 3: Render opt-in NetworkPolicies**

Emit policies only when enabled and document that policy objects do not imply
kindnet enforcement.

- [ ] **Step 4: Run ShellCheck and contracts**

Run: `shellcheck scripts/*.sh && python3 -m unittest tests.contract.test_scripts tests.contract.test_no_secrets -v`

Expected: pass without exposing credentials.

### Task 6: CI and user documentation

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Create: `docs/guide/application-deployment.md`
- Modify: `docs/.vitepress/config.mts`
- Modify: `docs/guide/quickstart.md`
- Modify: `docs/guide/sandbox-deployment.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document secret creation and offline rendering**

Provide copy-safe `kubectl create secret generic ... --from-literal` examples
with placeholders, preflight invocation, Helm 3/4 rollback flags, production
digest requirements, rollback, and verification commands.

- [ ] **Step 2: Expand kubeconform matrices**

Render enabled development workloads with a Secret reference and production
workloads with valid placeholder digests; validate without starting Pods.

- [ ] **Step 3: Build docs and validate manifests**

Run: `make validate`, `pnpm --dir docs build`, and all documented kubeconform
pipelines. Expected: all pass.

### Task 7: Review and publish

**Files:**
- Modify only files required by review findings.

- [ ] **Step 1: Review the full diff**

Check fixed Gateway names, no plaintext secrets, default-disabled behavior,
production digest enforcement, namespace-scoped RBAC, and compatible security
contexts.

- [ ] **Step 2: Commit and publish**

Commit with `feat(helm): add application workloads`, push
`codex/application-workloads`, and open a Draft PR with base
`codex/sandbox-helm` linked to Issue #5.

- [ ] **Step 3: Monitor CI**

Inspect failing logs, fix code-owned failures, and record external blockers
without starting application workloads.

