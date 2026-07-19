import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/coderushoj"


class ApplicationRenderTest(unittest.TestCase):
    def render(self, *extra_args):
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                "--set",
                "applications.enabled=true",
                *extra_args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def test_default_profile_does_not_pull_unpublished_application_images(self):
        result = subprocess.run(
            ["helm", "template", "coderushoj", str(CHART), "--namespace", "coderushoj"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("kind: Deployment", result.stdout)
        self.assertNotIn("ghcr.io/coderushoj/", result.stdout)

    def test_kind_application_profile_requires_preloaded_images(self):
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                "--values",
                str(CHART / "values-kind.yaml"),
                "--values",
                str(CHART / "values-kind-app.yaml"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertGreaterEqual(result.stdout.count("kind: Deployment"), 5)
        self.assertEqual(5, result.stdout.count("imagePullPolicy: Never"))
        self.assertIn("name: coderushoj-judge-api", result.stdout)

    def test_renders_all_product_workloads_and_services(self):
        rendered = self.render()
        for component in ("frontend", "backend", "docs", "judging-server", "sandbox"):
            self.assertIn(f"app.kubernetes.io/component: {component}", rendered)
        self.assertGreaterEqual(rendered.count("kind: Deployment"), 5)
        self.assertGreaterEqual(rendered.count("kind: Service"), 5)
        self.assertNotIn(":latest", rendered)
        self.assertIn("kind: PersistentVolumeClaim", rendered)
        self.assertIn("mountPath: /app/uploads", rendered)

    def test_sandbox_is_discovered_through_headless_service_dns(self):
        rendered = self.render()
        self.assertIn("name: sandbox-workers", rendered)
        self.assertIn("clusterIP: None", rendered)
        self.assertIn("publishNotReadyAddresses: false", rendered)
        self.assertIn("name: grpc", rendered)
        self.assertIn("containerPort: 50051", rendered)
        self.assertIn(
            'value: "dns:///sandbox-workers.coderushoj.svc.cluster.local:50051"',
            rendered,
        )
        self.assertIn("name: SANDBOX_ALLOW_LEGACY_ENDPOINT_SLICE\n              value: \"false\"", rendered)
        self.assertNotIn("kind: Role", rendered)
        self.assertNotIn("kind: ClusterRole", rendered)

    def test_external_async_rest_is_explicit_and_separately_routed(self):
        rendered = self.render("--values", str(CHART / "values-kind.yaml"))
        self.assertIn('hostname: "judge.coderushoj.local"', rendered)
        self.assertIn("value: /api/v1", rendered)
        self.assertIn("name: EXTERNAL_API_ENABLED\n              value: \"true\"", rendered)
        self.assertIn("name: EXTERNAL_API_LISTEN_ADDRESS\n              value: \"0.0.0.0:8081\"", rendered)
        self.assertIn("name: external-http", rendered)
        self.assertIn("containerPort: 8081", rendered)
        self.assertIn("path: /livez", rendered)
        self.assertIn("path: /readyz", rendered)
        private_render = self.render()
        self.assertNotIn("name: coderushoj-judge-api", private_render)

    def test_runtime_secrets_are_references_and_never_inline(self):
        rendered = self.render()
        for key in (
            "mysql-password",
            "redis-password",
            "s3-access-key",
            "s3-secret-key",
            "jwt-secret",
            "judge-result-service-token",
            "external-api-auth-pepper-base64",
            "external-idempotency-pepper-base64",
            "external-cursor-key-base64",
            "external-source-key-base64",
            "smtp-password",
        ):
            self.assertIn(f"key: {key}", rendered)
        self.assertNotIn("replace-with", rendered)
        self.assertIn("name: SMTP_HOST", rendered)
        self.assertIn('value: "coderushoj-infra-mailpit"', rendered)
        for setting in (
            "SPRING_MAIL_PROPERTIES_MAIL_SMTP_AUTH",
            "SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_ENABLE",
            "SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_REQUIRED",
            "SPRING_MAIL_PROPERTIES_MAIL_SMTP_SSL_ENABLE",
        ):
            self.assertIn(f"name: {setting}\n              value: \"false\"", rendered)

    def test_first_administrator_job_is_explicit_one_shot_and_secret_only(self):
        default_render = self.render()
        self.assertNotIn("name: coderushoj-admin-bootstrap\n", default_render)
        self.assertNotIn("BOOTSTRAP_ADMIN_PASSWORD", default_render)

        rendered = self.render("--set", "bootstrapAdmin.enabled=true")
        self.assertIn("kind: Job", rendered)
        self.assertIn("name: coderushoj-admin-bootstrap\n", rendered)
        self.assertIn("name: CROJ_MODE\n", rendered)
        self.assertIn('value: "bootstrap-admin"', rendered)
        self.assertIn("name: BOOTSTRAP_ADMIN_USERNAME", rendered)
        self.assertIn("name: BOOTSTRAP_ADMIN_EMAIL", rendered)
        self.assertIn("name: BOOTSTRAP_ADMIN_PASSWORD", rendered)
        for key in ("username", "email", "password"):
            self.assertIn(f"key: {key}", rendered)
        self.assertIn("name: coderushoj-admin-bootstrap-secret", rendered)
        self.assertIn("automountServiceAccountToken: false", rendered)
        self.assertIn("readOnlyRootFilesystem: true", rendered)
        self.assertIn("restartPolicy: Never", rendered)
        self.assertIn("backoffLimit: 1", rendered)
        self.assertIn("activeDeadlineSeconds: 300", rendered)
        policy_start = rendered.index("name: coderushoj-admin-bootstrap-egress\n")
        policy_end = rendered.index("name: coderushoj-application-egress\n")
        bootstrap_policy = rendered[policy_start:policy_end]
        self.assertIn("port: 3306", bootstrap_policy)
        self.assertIn("app.kubernetes.io/component: mysql", bootstrap_policy)
        for forbidden_port in (6379, 7999, 8333, 9876, 50051, 443):
            self.assertNotIn(f"port: {forbidden_port}", bootstrap_policy)

        backend_start = rendered.index("name: croj-backend\n")
        bootstrap_start = rendered.index("name: coderushoj-admin-bootstrap\n")
        backend_manifest = rendered[backend_start:bootstrap_start]
        self.assertNotIn("BOOTSTRAP_ADMIN_", backend_manifest)
        self.assertNotIn("CROJ_MODE", backend_manifest)

    def test_bootstrap_job_requires_a_dedicated_secret_name(self):
        result = subprocess.run(
            [
                "helm", "template", "coderushoj", str(CHART),
                "--namespace", "coderushoj",
                "--set", "applications.enabled=true",
                "--set", "bootstrapAdmin.enabled=true",
                "--set", "bootstrapAdmin.secretName=",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("bootstrapAdmin/secretName", result.stderr)

    def test_workloads_have_probes_resources_and_bounded_security_contexts(self):
        rendered = self.render()
        self.assertGreaterEqual(rendered.count("readinessProbe:"), 5)
        self.assertGreaterEqual(rendered.count("livenessProbe:"), 5)
        self.assertGreaterEqual(rendered.count("resources:"), 5)
        self.assertGreaterEqual(rendered.count("automountServiceAccountToken: false"), 5)
        self.assertGreaterEqual(rendered.count("enableServiceLinks: false"), 5)
        self.assertIn("coderushoj.io/sandbox: \"true\"", rendered)
        self.assertIn("kind: NetworkPolicy", rendered)
        self.assertIn("name: coderushoj-backend-internal-ingress", rendered)
        self.assertIn("kind: PodDisruptionBudget", rendered)
        self.assertGreaterEqual(rendered.count("mountPath: /var/cache/nginx"), 2)
        self.assertGreaterEqual(rendered.count("mountPath: /var/run"), 2)

    def test_values_schema_rejects_invalid_sandbox_concurrency(self):
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                "--set",
                "sandbox.maxConcurrency=0",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("/sandbox/maxConcurrency", result.stderr)

    def test_external_route_cannot_be_exposed_when_listener_is_disabled(self):
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--set",
                "applications.enabled=true",
                "--set",
                "judgingServer.externalAPI.enabled=false",
                "--set",
                "judgingServer.externalAPI.expose=true",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("externalAPI/enabled", result.stderr)

        disabled = self.render(
            "--set",
            "judgingServer.externalAPI.enabled=false",
            "--set",
            "judgingServer.externalAPI.expose=false",
        )
        self.assertGreaterEqual(disabled.count("name: croj-backend"), 2)
        self.assertEqual(1, disabled.count("name: croj-judging-server"))
        for key in (
            "external-api-auth-pepper-base64",
            "external-idempotency-pepper-base64",
            "external-cursor-key-base64",
            "external-source-key-base64",
        ):
            self.assertNotIn(key, disabled)
        self.assertNotIn("containerPort: 8081", disabled)

    def test_production_requires_digest_pinned_images(self):
        digest = "sha256:" + "a" * 64
        digest_args = sum(
            (
                ["--set-string", f"images.{name}.digest={digest}"]
                for name in ("frontend", "backend", "judgingServer", "sandbox", "docs")
            ),
            [],
        )
        smtp_args = [
            "--set", "backend.smtp.host=smtp.operator.example",
            "--set", "backend.smtp.username=coderushoj@operator.example",
        ]
        production_args = [*digest_args, *smtp_args]
        rendered = self.render(
            "--values",
            str(CHART / "values-production.yaml"),
            *production_args,
        )
        self.assertGreaterEqual(rendered.count("image: ghcr.io/coderushoj/"), 4)
        self.assertIn("image: ghcr.io/coderushoj/coderushoj-docs@sha256:", rendered)
        self.assertGreaterEqual(rendered.count("@sha256:"), 5)
        self.assertNotIn("imagePullPolicy: Always", rendered)
        self.assertGreaterEqual(rendered.count("protocol: HTTPS"), 2)
        self.assertGreaterEqual(rendered.count("name: coderushoj-web-tls"), 2)

        failure = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                "--values",
                str(CHART / "values-production.yaml"),
                *smtp_args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, failure.returncode)
        self.assertIn("production image digest is required", failure.stderr)

        unsafe_judge = subprocess.run(
            [
                "helm", "template", "coderushoj", str(CHART),
                "--namespace", "coderushoj",
                "--values", str(CHART / "values-production.yaml"),
                *production_args,
                "--set", "judgingServer.externalAPI.expose=true",
                "--set", "judgingServer.externalAPI.tls.enabled=false",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, unsafe_judge.returncode)
        self.assertIn("externalAPI/tls/enabled", unsafe_judge.stderr)

        secure_judge = self.render(
            "--values", str(CHART / "values-production.yaml"),
            *production_args,
            "--set", "judgingServer.externalAPI.expose=true",
            "--set", "judgingServer.externalAPI.tls.enabled=true",
            "--set", "judgingServer.externalAPI.tls.secretName=coderushoj-judge-tls",
        )
        self.assertIn('hostname: "judge.oj.example.com"', secure_judge)
        self.assertIn("name: coderushoj-judge-tls", secure_judge)

        missing_smtp = subprocess.run(
            [
                "helm", "template", "coderushoj", str(CHART),
                "--namespace", "coderushoj",
                "--values", str(CHART / "values-production.yaml"),
                *digest_args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, missing_smtp.returncode)
        self.assertIn("/backend/smtp", missing_smtp.stderr)


if __name__ == "__main__":
    unittest.main()
