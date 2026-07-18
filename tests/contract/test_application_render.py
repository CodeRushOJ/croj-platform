import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/coderushoj"
SECRET_NAME = "coderushoj-application"
DIGEST = "sha256:" + ("b" * 64)


class ApplicationRenderTest(unittest.TestCase):
    def helm(self, *extra_args):
        return subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                *extra_args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def render(self, *extra_args):
        result = self.helm(*extra_args)
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def test_application_workloads_are_disabled_by_default(self):
        rendered = self.render()

        for name in ("croj-backend", "croj-frontend", "croj-judging-server"):
            self.assertNotIn(f"kind: Deployment\nmetadata:\n  name: {name}", rendered)
        self.assertNotIn("name: coderushoj-judging-server-endpointslices", rendered)

    def test_backend_workload(self):
        rendered = self.render(
            "--set", "backend.enabled=true",
            "--set", f"backend.existingSecret.name={SECRET_NAME}",
        )

        self.assertIn("kind: Service\nmetadata:\n  name: croj-backend", rendered)
        self.assertIn("name: http\n      port: 7999\n      targetPort: http", rendered)
        self.assertIn("kind: Deployment\nmetadata:\n  name: croj-backend", rendered)
        self.assertIn('image: "ghcr.io/coderushoj/croj-backend:0.1.0"', rendered)
        self.assertIn("containerPort: 7999", rendered)
        self.assertIn("path: /api/actuator/health/readiness", rendered)
        self.assertIn("path: /api/actuator/health/liveness", rendered)
        self.assertIn("readOnlyRootFilesystem: true", rendered)
        self.assertIn("allowPrivilegeEscalation: false", rendered)
        self.assertIn("runAsNonRoot: true", rendered)
        self.assertIn("automountServiceAccountToken: false", rendered)
        self.assertIn("kind: PodDisruptionBudget\nmetadata:\n  name: croj-backend", rendered)
        self.assertIn("name: backend-uploads\n          emptyDir: {}", rendered)
        self.assertIn("mountPath: /app/uploads", rendered)
        self.assertIn("topologySpreadConstraints:", rendered)
        self.assertIn("podAntiAffinity:", rendered)
        for env_name, key in (
            ("DATABASE_USERNAME", "DATABASE_USERNAME"),
            ("DATABASE_PASSWORD", "DATABASE_PASSWORD"),
            ("REDIS_PASSWORD", "REDIS_PASSWORD"),
            ("JWT_SECRET", "JWT_SECRET"),
            ("SMTP_USERNAME", "SMTP_USERNAME"),
            ("SMTP_PASSWORD", "SMTP_PASSWORD"),
            ("JUDGE_RESULT_SERVICE_TOKEN", "JUDGE_RESULT_SERVICE_TOKEN"),
        ):
            self.assertIn(f"name: {env_name}", rendered)
            self.assertIn(f"name: {SECRET_NAME}\n                  key: {key}", rendered)
        self.assertIn("name: SUBMISSION_TOPIC\n              value: \"coderushoj.submission.v1\"", rendered)
        self.assertIn("name: SPRING_PROFILES_ACTIVE\n              value: \"prod\"", rendered)
        self.assertIn(
            "name: REDIS_HOST\n              value: \"coderushoj-infra-redis.coderushoj.svc\"",
            rendered,
        )

    def test_frontend_workload(self):
        rendered = self.render("--set", "frontend.enabled=true")

        self.assertIn("kind: Service\nmetadata:\n  name: croj-frontend", rendered)
        self.assertIn("name: http\n      port: 80\n      targetPort: http", rendered)
        self.assertIn("kind: Deployment\nmetadata:\n  name: croj-frontend", rendered)
        self.assertIn('image: "ghcr.io/coderushoj/croj-frontend:0.1.0"', rendered)
        self.assertIn("containerPort: 8080", rendered)
        self.assertGreaterEqual(rendered.count("path: /healthz"), 2)
        self.assertIn("runAsUser: 101", rendered)
        self.assertIn("readOnlyRootFilesystem: true", rendered)
        self.assertIn("kind: PodDisruptionBudget\nmetadata:\n  name: croj-frontend", rendered)
        self.assertIn("topologySpreadConstraints:", rendered)

    def test_judging_workload_reuses_endpoint_slice_rbac(self):
        rendered = self.render(
            "--set", "judgingServer.enabled=true",
            "--set", f"judgingServer.existingSecret.name={SECRET_NAME}",
        )

        self.assertIn("kind: Deployment\nmetadata:\n  name: croj-judging-server", rendered)
        self.assertNotIn("kind: Service\nmetadata:\n  name: croj-judging-server", rendered)
        self.assertIn("serviceAccountName: coderushoj-judging-server", rendered)
        self.assertIn("automountServiceAccountToken: true", rendered)
        self.assertIn("name: coderushoj-judging-server-endpointslices", rendered)
        self.assertIn("resources:\n      - endpointslices", rendered)
        self.assertIn("verbs:\n      - list", rendered)
        self.assertNotIn("kind: ClusterRole", rendered)
        for name, value in (
            ("ROCKETMQ_NAME_SERVER", "coderushoj-infra-rocketmq-namesrv.coderushoj.svc:9876"),
            ("SUBMISSION_TOPIC", "coderushoj.submission.v1"),
            ("ROCKETMQ_CONSUMER_GROUP", "coderushoj-judging-v1"),
            ("BACKEND_INTERNAL_URL", "http://croj-backend:7999/api"),
            ("JUDGE_RESULT_CALLBACK_TIMEOUT", "10s"),
            ("SANDBOX_NAMESPACE", "coderushoj"),
            ("SANDBOX_SERVICE", "croj-sandbox"),
            ("SANDBOX_PORT_NAME", "grpc"),
            ("SANDBOX_EXECUTE_TIMEOUT", "60s"),
            ("JUDGE_BUNDLE_CACHE_DIR", "/tmp/croj-bundles"),
            ("OBJECT_STORAGE_ENDPOINT", "coderushoj-infra-seaweedfs.coderushoj.svc:8333"),
            ("OBJECT_STORAGE_BUCKET", "coderushoj-testdata"),
            ("OBJECT_STORAGE_REGION", "us-east-1"),
            ("OBJECT_STORAGE_USE_TLS", "false"),
        ):
            self.assertIn(f"name: {name}\n              value: \"{value}\"", rendered)
        self.assertIn("name: JUDGE_RESULT_SERVICE_TOKEN", rendered)
        self.assertIn(
            f"name: {SECRET_NAME}\n                  key: JUDGE_RESULT_SERVICE_TOKEN",
            rendered,
        )
        self.assertNotIn("readinessProbe:", rendered)
        self.assertNotIn("livenessProbe:", rendered)
        self.assertIn("readOnlyRootFilesystem: true", rendered)
        self.assertIn("mountPath: /tmp", rendered)
        self.assertIn("sizeLimit: 2Gi", rendered)
        for key in ("OBJECT_STORAGE_ACCESS_KEY", "OBJECT_STORAGE_SECRET_KEY"):
            self.assertIn(f"key: {key}", rendered)
        self.assertIn("kind: PodDisruptionBudget\nmetadata:\n  name: croj-judging-server", rendered)

    def test_judging_bundle_cache_size_has_a_schema_cap(self):
        result = self.helm(
            "--set", "judgingServer.enabled=true",
            "--set", f"judgingServer.existingSecret.name={SECRET_NAME}",
            "--set", "judgingServer.config.bundleCacheSizeLimit=8Gi",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be one of", result.stderr)

    def test_secret_consuming_workloads_fail_without_an_external_secret_name(self):
        for component in ("backend", "judgingServer"):
            with self.subTest(component=component):
                result = self.helm("--set", f"{component}.enabled=true")
                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    f"{component}.existingSecret.name is required when {component}.enabled=true",
                    result.stderr,
                )

    def test_required_secret_key_mappings_cannot_be_empty(self):
        result = self.helm(
            "--set", "backend.enabled=true",
            "--set", f"backend.existingSecret.name={SECRET_NAME}",
            "--set", "backend.existingSecret.keys.jwtSecret=",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("/backend/existingSecret/keys/jwtSecret", result.stderr)

    def test_fixed_gateway_service_names_cannot_be_changed(self):
        for component, name in (("backend", "croj-backend"), ("frontend", "croj-frontend")):
            with self.subTest(component=component):
                result = self.helm("--set", f"{component}.service.name=renamed")
                self.assertNotEqual(0, result.returncode)
                self.assertIn(name, result.stderr)

        rendered = self.render(
            "--set", "services.backend.name=renamed-backend",
            "--set", "services.frontend.name=renamed-frontend",
        )
        self.assertNotIn("name: renamed-backend", rendered)
        self.assertNotIn("name: renamed-frontend", rendered)
        self.assertIn("name: croj-backend\n          port: 7999", rendered)
        self.assertIn("name: croj-frontend\n          port: 80", rendered)

    def test_production_enabled_workloads_require_immutable_images(self):
        production = str(CHART / "values-production.yaml")
        cases = (
            ("backend", (
                "--set", f"backend.existingSecret.name={SECRET_NAME}",
                "--set", "backend.storage.existingClaim=coderushoj-uploads",
            )),
            ("frontend", ()),
            ("judgingServer", ("--set", f"judgingServer.existingSecret.name={SECRET_NAME}")),
        )
        for component, secret_args in cases:
            with self.subTest(component=component):
                result = self.helm(
                    "--values", production,
                    "--set", f"{component}.enabled=true",
                    *secret_args,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn(f"{component}.image.digest is required", result.stderr)

    def test_production_images_render_by_digest(self):
        rendered = self.render(
            "--values", str(CHART / "values-production.yaml"),
            "--set", "backend.enabled=true",
            "--set", "frontend.enabled=true",
            "--set", "judgingServer.enabled=true",
            "--set", f"backend.existingSecret.name={SECRET_NAME}",
            "--set", "backend.storage.existingClaim=coderushoj-uploads",
            "--set", f"judgingServer.existingSecret.name={SECRET_NAME}",
            "--set-string", f"backend.image.digest={DIGEST}",
            "--set-string", f"frontend.image.digest={DIGEST}",
            "--set-string", f"judgingServer.image.digest={DIGEST}",
        )

        for repository in ("croj-backend", "croj-frontend", "croj-judging-server"):
            self.assertIn(f'image: "ghcr.io/coderushoj/{repository}@{DIGEST}"', rendered)
        self.assertIn("claimName: coderushoj-uploads", rendered)
        self.assertIn("mountPath: /app/uploads", rendered)

    def test_production_backend_requires_an_existing_persistent_claim(self):
        result = self.helm(
            "--values", str(CHART / "values-production.yaml"),
            "--set", "backend.enabled=true",
            "--set", f"backend.existingSecret.name={SECRET_NAME}",
            "--set-string", f"backend.image.digest={DIGEST}",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("backend.storage.existingClaim is required", result.stderr)

    def test_network_policies_are_explicitly_opt_in(self):
        default_render = self.render(
            "--set", "frontend.enabled=true",
            "--set", "backend.enabled=true",
            "--set", f"backend.existingSecret.name={SECRET_NAME}",
        )
        self.assertNotIn("kind: NetworkPolicy", default_render)

        policy_render = self.render(
            "--set", "frontend.enabled=true",
            "--set", "backend.enabled=true",
            "--set", "judgingServer.enabled=true",
            "--set", f"backend.existingSecret.name={SECRET_NAME}",
            "--set", f"judgingServer.existingSecret.name={SECRET_NAME}",
            "--set", "networkPolicy.enabled=true",
            "--set", "networkPolicy.external.smtpCidrs[0]=203.0.113.0/24",
            "--set", "networkPolicy.external.kubernetesApiCidrs[0]=10.96.0.1/32",
        )
        self.assertGreaterEqual(policy_render.count("kind: NetworkPolicy"), 3)
        self.assertIn("gateway.envoyproxy.io/owning-gateway-name: coderushoj", policy_render)
        self.assertIn("kubernetes.io/metadata.name: envoy-gateway-system", policy_render)
        self.assertIn("app.kubernetes.io/component: mysql", policy_render)
        self.assertIn("app.kubernetes.io/instance: coderushoj-infra", policy_render)
        self.assertIn("app.kubernetes.io/component: rocketmq-namesrv", policy_render)
        self.assertIn("app.kubernetes.io/component: rocketmq-broker", policy_render)
        self.assertGreaterEqual(policy_render.count("port: 10911"), 2)
        self.assertGreaterEqual(policy_render.count("port: 10909"), 2)
        self.assertIn("app.kubernetes.io/name: croj-sandbox", policy_render)
        self.assertIn("k8s-app: kube-dns", policy_render)
        self.assertIn("cidr: 203.0.113.0/24", policy_render)
        self.assertIn("cidr: 10.96.0.1/32", policy_render)
        self.assertNotIn("- {port: 443", policy_render)

    def test_network_policy_fails_closed_without_external_cidrs(self):
        backend = self.helm(
            "--set", "backend.enabled=true",
            "--set", f"backend.existingSecret.name={SECRET_NAME}",
            "--set", "networkPolicy.enabled=true",
        )
        self.assertNotEqual(0, backend.returncode)
        self.assertIn("networkPolicy.external.smtpCidrs", backend.stderr)

        judging = self.helm(
            "--set", "judgingServer.enabled=true",
            "--set", f"judgingServer.existingSecret.name={SECRET_NAME}",
            "--set", "networkPolicy.enabled=true",
        )
        self.assertNotEqual(0, judging.returncode)
        self.assertIn("networkPolicy.external.kubernetesApiCidrs", judging.stderr)

    def test_ci_kubeconform_validates_enabled_application_profiles(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        for contract in (
            "backend.enabled=true",
            "frontend.enabled=true",
            "judgingServer.enabled=true",
            "backend.existingSecret.name=coderushoj-application",
            "judgingServer.existingSecret.name=coderushoj-application",
            "backend.storage.existingClaim=coderushoj-uploads",
            "backend.image.digest=sha256:",
            "frontend.image.digest=sha256:",
            "judgingServer.image.digest=sha256:",
        ):
            self.assertIn(contract, workflow)


if __name__ == "__main__":
    unittest.main()
