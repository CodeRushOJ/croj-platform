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

    def network_policy(self, rendered, name):
        marker = f"kind: NetworkPolicy\nmetadata:\n  name: {name}\n"
        self.assertIn(marker, rendered, f"missing NetworkPolicy {name}")
        return marker + rendered.split(marker, 1)[1].split("\n---", 1)[0]

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

    def test_network_policies_are_release_scoped_and_target_specific(self):
        rendered = self.render()
        policy_names = (
            "coderushoj-default-deny",
            "coderushoj-web-ingress",
            "coderushoj-sandbox-ingress",
            "coderushoj-backend-internal-ingress",
            "coderushoj-dns-egress",
            "coderushoj-backend-dependencies-egress",
            "coderushoj-judging-dependencies-egress",
            "coderushoj-judging-redis-egress",
            "coderushoj-judging-internal-egress",
            "coderushoj-backend-smtp-egress",
            "coderushoj-judging-webhook-egress",
        )
        for name in policy_names:
            with self.subTest(policy=name):
                policy = self.network_policy(rendered, name)
                selected_pods = policy.split("policyTypes:", 1)[0]
                self.assertIn("app.kubernetes.io/instance: coderushoj", selected_pods)

        self.assertNotIn("podSelector: {}", rendered)
        self.assertNotIn("namespaceSelector: {}", rendered)

        dns = self.network_policy(rendered, "coderushoj-dns-egress")
        self.assertIn("kubernetes.io/metadata.name: kube-system", dns)
        self.assertIn("k8s-app: kube-dns", dns)
        self.assertIn("port: 53", dns)

        for policy_name in (
            "coderushoj-backend-dependencies-egress",
            "coderushoj-judging-dependencies-egress",
        ):
            policy = self.network_policy(rendered, policy_name)
            self.assertIn("app.kubernetes.io/instance: coderushoj-infra", policy)
            for component, port in (
                ("mysql", 3306),
                ("rocketmq-namesrv", 9876),
                ("rocketmq-broker", 10911),
                ("seaweedfs", 8333),
            ):
                self.assertIn(f"app.kubernetes.io/component: {component}", policy)
                self.assertIn(f"port: {port}", policy)

        backend_dependencies = self.network_policy(
            rendered,
            "coderushoj-backend-dependencies-egress",
        )
        self.assertIn("app.kubernetes.io/component: redis", backend_dependencies)
        self.assertIn("port: 6379", backend_dependencies)

        judging_redis = self.network_policy(
            rendered,
            "coderushoj-judging-redis-egress",
        )
        self.assertIn("app.kubernetes.io/instance: coderushoj-infra", judging_redis)
        self.assertIn("app.kubernetes.io/component: redis", judging_redis)
        self.assertIn("port: 6379", judging_redis)

        internal = self.network_policy(rendered, "coderushoj-judging-internal-egress")
        for component, port in (("backend", 7999), ("sandbox", 50051)):
            self.assertIn("app.kubernetes.io/instance: coderushoj", internal)
            self.assertIn(f"app.kubernetes.io/component: {component}", internal)
            self.assertIn(f"port: {port}", internal)

        sandbox_ingress = self.network_policy(rendered, "coderushoj-sandbox-ingress")
        self.assertIn("port: 50051", sandbox_ingress)
        self.assertNotIn("port: 1025", sandbox_ingress)

    def test_judge_network_authorizations_follow_external_api_flags(self):
        internal_only = self.render()
        shared_web = self.network_policy(internal_only, "coderushoj-web-ingress")
        self.assertNotIn("judging-server", shared_web)
        self.assertNotIn("name: coderushoj-judge-web-ingress", internal_only)
        self.assertIn("name: coderushoj-judging-redis-egress", internal_only)

        exposed = self.render("--values", str(CHART / "values-kind.yaml"))
        judge_web = self.network_policy(exposed, "coderushoj-judge-web-ingress")
        self.assertIn("app.kubernetes.io/instance: coderushoj", judge_web)
        self.assertIn("app.kubernetes.io/component: judging-server", judge_web)
        self.assertIn("kubernetes.io/metadata.name: envoy-gateway-system", judge_web)
        self.assertIn("port: 8081", judge_web)

        disabled = self.render(
            "--set",
            "judgingServer.externalAPI.enabled=false",
            "--set",
            "judgingServer.externalAPI.expose=false",
        )
        self.assertNotIn("name: coderushoj-judge-web-ingress", disabled)
        self.assertNotIn("name: coderushoj-judging-redis-egress", disabled)
        judging_dependencies = self.network_policy(
            disabled,
            "coderushoj-judging-dependencies-egress",
        )
        self.assertNotIn("app.kubernetes.io/component: redis", judging_dependencies)

    def test_smtp_egress_uses_profile_port_and_external_scope(self):
        development = self.render()
        local_smtp = self.network_policy(development, "coderushoj-backend-smtp-egress")
        self.assertIn("app.kubernetes.io/instance: coderushoj-infra", local_smtp)
        self.assertIn("app.kubernetes.io/component: mailpit", local_smtp)
        self.assertIn("port: 1025", local_smtp)
        self.assertNotIn("cidr: 0.0.0.0/0", local_smtp)

        digest = "sha256:" + "a" * 64
        digest_args = sum(
            (
                ["--set-string", f"images.{name}.digest={digest}"]
                for name in ("frontend", "backend", "judgingServer", "sandbox", "docs")
            ),
            [],
        )
        production = self.render(
            "--values",
            str(CHART / "values-production.yaml"),
            *digest_args,
            "--set",
            "backend.smtp.host=smtp.operator.example",
            "--set",
            "backend.smtp.username=coderushoj@operator.example",
        )
        external_smtp = self.network_policy(production, "coderushoj-backend-smtp-egress")
        self.assertIn("cidr: 0.0.0.0/0", external_smtp)
        self.assertIn("cidr: ::/0", external_smtp)
        self.assertIn("port: 465", external_smtp)
        self.assertNotIn("app.kubernetes.io/component: mailpit", external_smtp)

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
