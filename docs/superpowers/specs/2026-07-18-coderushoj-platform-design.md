# CodeRushOJ Platform Design

**Status:** Approved architecture with quality requirements incorporated  
**Date:** 2026-07-18  
**Target release:** v1.0.0  

## 1. Product Goal

CodeRushOJ v1.0.0 is a self-hosted online judge that runs completely on a local Kubernetes cluster while retaining a production-shaped architecture. It supports user and administrator workflows, problem authoring, hidden test data, real code judging, ACM/OI contests, a forum, problem solutions, release documentation, and repeatable deployment.

The acceptance target is 1,000 online users, 100 concurrent submissions, and 20 parallel judge jobs on the reference local cluster. Services must scale horizontally without losing a submission or counting an accepted result twice.

Paid features are outside v1.0.0.

## 2. Repository Boundaries

The organization retains four service repositories and adds one platform repository.

| Repository | Responsibility |
| --- | --- |
| `croj-frontend` | Vue user application, contest UI, community UI, administration UI |
| `croj-backend` | Spring Boot business API and background outbox publisher |
| `croj-judging-server` | RocketMQ consumer, idempotent judge orchestration, Kubernetes Job lifecycle |
| `croj-sandbox` | One-shot, language-aware runner used as the Kubernetes Job workload |
| `croj-platform` | Docker Compose developer stack, Helm charts, local cluster automation, end-to-end tests, architecture and operations documentation, release train configuration |

Each repository builds and tests independently. `croj-platform` pins compatible image versions and owns cross-repository integration tests.

## 3. Runtime Architecture

### 3.1 Edge and application services

Gateway API Standard Channel resources expose three local routes through Envoy Gateway: the Vue application, `/api`, and the documentation site. The frontend is served by an unprivileged static web container. The backend runs as a stateless Deployment with readiness, liveness, and startup probes. The platform does not introduce ingress-nginx, which was retired upstream in March 2026.

The backend is a modular monolith. It is split by business capability rather than by controller/service/mapper technical layers. Every module exposes an application API and keeps persistence adapters private. Cross-module calls use explicit interfaces or domain events.

The initial modules are:

- identity and access;
- users and moderation;
- problems, versions, tags, and test data;
- submissions and judge events;
- contests, registration, clarification, and scoreboards;
- forum, comments, reactions, bookmarks, and reports;
- solutions and editorial moderation;
- notifications and audit records;
- object storage and administration.

### 3.2 Data services

- MySQL is the source of truth for business data, submission state, and the transactional outbox.
- Redis stores rate-limit counters, short-lived verification data, hot scoreboards, and revocation state. Redis is never the sole source of durable business data.
- SeaweedFS exposes an S3-compatible object API and stores versioned hidden test bundles, avatars, forum attachments, and solution images. Object keys are opaque and private by default. Application code depends only on the S3 contract so the implementation remains replaceable.
- RocketMQ carries judge commands and dead-letter events. Message payloads contain identifiers and version metadata, not source code or test data.

Schema changes use ordered Flyway migrations. Existing DDL is converted into the baseline migration. Development seed data is repeatable and includes an administrator, tags, example users, a problem with hidden tests, a contest, forum content, and a published solution. Production migrations never insert fixed passwords.

### 3.3 Judge delivery and execution

Creating a submission writes the submission and an outbox event in one MySQL transaction. A publisher claims unsent events, publishes them to RocketMQ, and marks them sent. Publishing is repeatable; consumers must therefore be idempotent.

The judging server consumes commands in a shared consumer group. It claims a pending submission with a conditional state transition, resolves the immutable problem/test-data version, and creates a Kubernetes Job. Kubernetes schedules jobs across worker nodes; ZooKeeper is removed.

Each Job has:

- a trusted init step that fetches the immutable test bundle into an `emptyDir` volume;
- a one-shot runner that compiles once, executes every test group, applies scoring, and writes a bounded structured result to logs;
- `runAsNonRoot`, a read-only root filesystem, dropped Linux capabilities, `allowPrivilegeEscalation: false`, `RuntimeDefault` seccomp, CPU/memory/ephemeral-storage quotas, process limits, an active deadline, and automatic TTL cleanup;
- an egress policy restricted to the object-store endpoint required during preparation, with no credentials mounted in the runner container.

The orchestrator watches Job and Pod state, validates the result schema, and commits the terminal submission status with compare-and-set semantics. Accepted counters and contest scoreboard changes occur in the same transaction as the terminal result. Retryable infrastructure failures use bounded exponential backoff. Exhausted work enters a dead-letter topic and becomes `SYSTEM_ERROR` with an operator-visible reason.

Supported languages are C11, C++17, Java 17, Python 3, Go, and JavaScript on Node.js. Compiler/runtime images are version-pinned and recorded on every submission so results remain explainable after upgrades.

## 4. Functional Design

### 4.1 Identity and permissions

Users can register, sign in, refresh and revoke sessions, verify email, reset a password, edit a profile, and upload an avatar. Passwords use an adaptive password hash. Short-lived access tokens and rotating refresh tokens are stored separately. Administrative permissions are enforced in the backend even when the frontend hides an action.

Roles are user, problem setter, moderator, administrator, and platform owner. Audit records capture security-sensitive and administrative changes without storing secrets or full source code.

### 4.2 Problems and submissions

A problem has immutable published versions. A version contains statement sections, samples, limits, language policy, judge mode, test groups, weights, and an optional special-judge definition. Hidden data is never returned through public problem endpoints.

ACM mode stops at the first decisive failure and produces a single verdict. OI mode evaluates all configured groups and returns a score. Special judges run as separately versioned restricted workloads and receive only contestant output and expected metadata.

Submission states are `PENDING`, `DISPATCHING`, `RUNNING`, and terminal verdicts. State changes are monotonic. Rejudge creates a new judge attempt while retaining the original result history.

### 4.3 Contests

Contests support public and invite-only access, registration windows, ACM and OI rules, problem visibility windows, announcements, clarifications, penalties, scoreboard freezing, unfreezing, and post-contest rejudge. Scoreboard rows are derived from accepted submission history and can be rebuilt from MySQL.

### 4.4 Forum and solutions

The forum supports categories, posts, nested one-level replies, reactions, bookmarks, reports, soft deletion, moderation, and lock/pin controls. Solutions are tied to a problem version and support drafts, publishing, reactions, bookmarks, reports, and administrator/editorial highlighting.

User-authored content uses Markdown with a strict sanitizer. Raw script, unsafe URL schemes, event attributes, and arbitrary iframes are rejected. Attachments use type, size, and ownership validation and are served with safe content-disposition headers.

## 5. Frontend Experience and Visual Quality

The frontend is redesigned around a documented token system instead of isolated page styles. Tokens cover color, typography, spacing, radii, elevation, motion, breakpoints, and semantic judge statuses. Components use consistent focus, hover, active, loading, empty, error, and disabled states.

The product has three coherent surfaces:

- the public/user surface emphasizes fast problem discovery, a distraction-free split problem/editor view, live submission status, contest focus, and readable community content;
- the administration surface uses dense but legible tables, saved filters, bulk actions, clear destructive-action confirmation, and audit context;
- the documentation surface shares branding while prioritizing navigation and code readability.

Visual acceptance criteria are explicit:

- responsive layouts at 360 px, 768 px, 1280 px, and 1536 px;
- keyboard navigation and visible focus for all interactive controls;
- WCAG AA contrast for normal text and status indicators that do not depend on color alone;
- no layout shift during primary loading states;
- reusable empty, error, permission-denied, and not-found pages;
- route-level code splitting and a measured production bundle budget;
- Playwright screenshot baselines for the home, problem list, problem workspace, contest scoreboard, forum, solution, and administration dashboard.

The existing logo and useful workflows are retained, but template README content and inconsistent one-off styling are removed.

## 6. Backend Engineering Rules

The backend uses package-by-feature with ports and adapters at external boundaries. Controllers translate HTTP input and output only. Application services own use-case orchestration and transaction boundaries. Domain objects enforce state transitions. Repositories hide MyBatis/JPA details. RocketMQ, Redis, S3-compatible object storage, mail, and Kubernetes clients are adapters behind interfaces.

API contracts use consistent problem details, stable error codes, request correlation IDs, cursor or bounded page pagination, validation, and generated OpenAPI documentation. Logs are structured and redact tokens, passwords, verification codes, hidden test contents, and contestant source.

External calls have timeouts, bounded retries with jitter, and metrics. Retry is not used for validation failures or non-idempotent operations without an idempotency key. Database indexes are justified by actual query paths and verified with integration tests.

## 7. Testing Strategy

Tests are production artifacts and remain in the repositories.

### 7.1 Frontend

- Vitest covers stores, composables, validators, API error mapping, and domain-formatting logic.
- Vue Test Utils covers reusable components, permission states, forms, and loading/error behavior.
- Mock Service Worker provides deterministic API fixtures.
- Playwright covers critical workflows and screenshot regression baselines.

### 7.2 Backend

- Plain unit tests cover domain rules and state machines without Spring context.
- slice tests cover MVC validation/security and persistence mappings.
- Testcontainers integration tests use real MySQL, Redis, RocketMQ, and S3-compatible services where the boundary matters.
- migration tests create a database from zero and upgrade from the previous release schema.
- authorization tests enumerate role/resource/action combinations.

### 7.3 Judge and sandbox

- Go unit tests cover message decoding, claim/idempotency behavior, result mapping, scoring, comparison, limits, and retry classification.
- Kubernetes fake-client tests cover Job manifests and lifecycle edge cases.
- Linux integration tests compile and execute all supported languages and assert every verdict.
- negative tests attempt fork bombs, memory exhaustion, filesystem escape, network access, oversized output, signal abuse, and timeout evasion.

### 7.4 Platform

A three-node Kind pipeline installs the complete chart and runs an end-to-end suite covering registration, administration, problem creation, hidden data upload, all-language judging, contest scoring, forum posting, and solution publication. CI retains logs, manifests, screenshots, and failed Pod diagnostics.

## 8. Observability and Operations

All services expose health and Prometheus endpoints. Dashboards show HTTP latency/error rate, outbox lag, RocketMQ consumer lag, submission queue time, judge duration/verdict distribution, Kubernetes Job failures, database pool state, and object-store failures.

Runbooks cover installation, upgrade, rollback, secret rotation, database backup/restore, stuck submissions, dead-letter replay, worker-node failure, and test-data recovery. Local installation is automated with idempotent scripts and Helm values rather than undocumented shell history.

Docker Compose provides the shortest single-host development path for the pinned stateful dependencies. The three-node Kind and Helm path is the reference acceptance environment because it also exercises Gateway API, worker placement, Kubernetes-native Service/Endpoint discovery, and judge-job scheduling. Both paths generate local secret files and use the same dependency versions; neither requires MySQL, Redis, RocketMQ, or object storage to be installed directly on the host.

## 9. Git, Issues, and Releases

Work is tracked as GitHub milestones and issues. Epics group platform foundation, core OJ, contests, community, and v1 hardening. Repositories provide feature, bug, security, documentation, and release issue templates.

Branches use `codex/issue-<number>-<short-name>`. Commits follow Conventional Commits and reference the issue. Pull requests include behavior, tests, migration impact, screenshots for UI work, operational impact, and rollback notes.

All repositories use semantic versioning. CI publishes immutable commit-SHA images on the main branch. A coordinated release pins service versions in `croj-platform`, generates `CHANGELOG.md`, publishes release notes and versioned images, and bumps the Helm chart. Release notes separate features, fixes, security, migrations, known limitations, and upgrade steps.

Development releases progress from v0.1.0. v1.0.0 requires all functional acceptance tests, security tests, documentation checks, a clean installation, an upgrade rehearsal, and a restore rehearsal to pass.

## 10. Delivery Decomposition

The system is delivered as independently testable increments:

1. Platform foundation: repositories, CI, local three-node cluster, charts, secrets, MySQL/Redis/RocketMQ/SeaweedFS, migrations, documentation shell, and release governance.
2. Core OJ: identity, problem/test-data management, real judge pipeline, submission UI, administrator workflows, and all-language tests.
3. Contests: registration, ACM/OI rules, clarifications, freeze/unfreeze, rebuildable scoreboards, and rejudge.
4. Community: forum, solutions, moderation, attachments, sanitization, and search.
5. v1 hardening: load tests, sandbox adversarial tests, accessibility and visual regression, backup/restore, upgrade/rollback, and v1.0.0 release.

Every increment must deploy successfully and keep the previously completed end-to-end suite green.

## 11. Explicit Non-goals for v1.0.0

- payments, subscriptions, or commercial licensing;
- public-cloud managed-service integration;
- native mobile applications;
- arbitrary user-provided interactive judges;
- multi-region active-active deployment.
