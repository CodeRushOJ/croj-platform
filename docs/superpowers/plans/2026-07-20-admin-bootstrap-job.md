# First Administrator Kubernetes Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision the first CodeRushOJ super administrator through an opt-in, Secret-only Kubernetes Job without exposing a default password to the long-running backend.

**Architecture:** The application chart reuses the digest-pinned Backend image in `CROJ_MODE=bootstrap-admin`. A dedicated identity Secret is mounted only as environment references in a non-root, tokenless, read-only Job whose NetworkPolicy permits DNS and MySQL only. The local helper generates a random password under `.workspace/secrets`, renders only the Job template, and safely distinguishes an existing Job from an explicit `--rerun`.

**Tech Stack:** Helm 4 JSON schema/templates, Kubernetes Job/Secret/NetworkPolicy, Bash, Python unittest, ShellCheck.

---

### Task 1: Lock the render and secret contracts with failing tests

**Files:**
- Modify: `tests/contract/test_application_render.py`
- Modify: `tests/contract/test_no_secrets.py`
- Modify: `tests/contract/test_scripts.py`

- [x] Write a failing default-disabled/enabled render test for the Job, image, mode, Secret references, security context, deadline, retry limit, and long-running Deployment isolation.
- [x] Write a failing schema test proving an enabled Job rejects an empty dedicated Secret name.
- [x] Write failing generator and script tests proving the three identity files stay separate and the password is never printed.
- [x] Run the focused Python tests and record the expected three render/generator failures plus missing-script failure.

### Task 2: Render the least-privilege Job

**Files:**
- Create: `charts/coderushoj/templates/admin-bootstrap-job.yaml`
- Modify: `charts/coderushoj/templates/network-policies.yaml`
- Modify: `charts/coderushoj/values.yaml`
- Modify: `charts/coderushoj/values.schema.json`

- [x] Make `bootstrapAdmin.enabled=false` the default and require `applications.enabled=true` plus a non-empty Secret name when enabled.
- [x] Reuse the Backend image helper so production requires the same immutable digest and Kind uses its preloaded `:dev` image.
- [x] Add `restartPolicy: Never`, `backoffLimit: 1`, five-minute deadline, ten-minute TTL, non-root UID/GID, RuntimeDefault seccomp, read-only rootfs, dropped capabilities, no ServiceAccount token, and bounded `/tmp`.
- [x] Restrict Job egress to cluster DNS and same-namespace MySQL port 3306; explicitly test absence of Redis, backend, S3, RocketMQ, sandbox, and public HTTPS ports.

### Task 3: Generate and operate the one-time identity safely

**Files:**
- Modify: `scripts/generate-secrets.sh`
- Create: `scripts/bootstrap-admin.sh`

- [x] Generate stable local username/email plus a random 24-byte password in `0600` ignored files.
- [x] Create `coderushoj-admin-bootstrap-secret` separately from runtime secrets using only `--from-file` and dry-run/apply.
- [x] Render only `templates/admin-bootstrap-job.yaml`, wait for the authoritative completion condition, and expose logs only on failure.
- [x] Treat an existing Job as authoritative; delete exactly that Job only after the operator passes `--rerun`.
- [x] Print only the local username and password-file path, never credential contents.

### Task 4: Document and validate

**Files:**
- Modify: `README.md`
- Modify: `docs/guide/quickstart.md`
- Modify: `CHANGELOG.md`

- [x] Document local and production Secret creation, first execution, rerun semantics, cleanup, credential rotation, and prohibited command-line/values storage.
- [x] Run all 52 platform contract tests, docs build, Helm lint, ShellCheck, and `git diff --check` without starting application services.
- [ ] Request an independent review, commit, push, and open a Draft PR stacked on `codex/application-runtime` and linked to platform issue #11.
