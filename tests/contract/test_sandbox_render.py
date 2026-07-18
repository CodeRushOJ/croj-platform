import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/coderushoj"


class SandboxRenderTest(unittest.TestCase):
    def render(self, *extra_args):
        result = subprocess.run(
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
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def test_default_profile_exposes_ready_grpc_endpoints_safely(self):
        rendered = self.render("--set", "sandbox.enabled=true")

        self.assertIn("kind: Deployment\nmetadata:\n  name: croj-sandbox", rendered)
        self.assertIn("kind: Service\nmetadata:\n  name: croj-sandbox", rendered)
        self.assertGreaterEqual(rendered.count("app.kubernetes.io/name: croj-sandbox"), 4)
        self.assertIn("name: grpc\n      port: 50051\n      targetPort: grpc", rendered)
        self.assertEqual(3, rendered.count("grpc:\n              port: 50051"))
        self.assertIn("fieldPath: metadata.uid", rendered)
        self.assertIn("name: CROJ_SANDBOX_INSTANCE_ID", rendered)
        self.assertIn("- -max-concurrency=2", rendered)
        self.assertIn('coderushoj.io/sandbox-worker: "true"', rendered)
        self.assertIn("automountServiceAccountToken: false", rendered)
        self.assertIn("privileged: false", rendered)
        self.assertIn("allowPrivilegeEscalation: false", rendered)
        self.assertIn("runAsNonRoot: true", rendered)
        self.assertNotIn("hostPath:", rendered)
        self.assertNotIn("kind: NetworkPolicy\nmetadata:\n  name: croj-sandbox", rendered)

    def test_sandbox_network_policy_is_opt_in(self):
        rendered = self.render(
            "--set", "sandbox.enabled=true",
            "--set", "sandbox.networkPolicy.enabled=true",
        )

        self.assertIn("kind: NetworkPolicy\nmetadata:\n  name: croj-sandbox", rendered)
        self.assertIn("app.kubernetes.io/name: croj-judging-server", rendered)
        self.assertIn("policyTypes:\n    - Ingress\n    - Egress", rendered)

    def test_kind_profile_uses_development_only_cgroup_privileges(self):
        rendered = self.render(
            "--values",
            str(CHART / "values-kind.yaml"),
            "--set",
            "sandbox.enabled=true",
        )

        self.assertIn('coderushoj.io/judge-worker: "true"', rendered)
        self.assertIn("privileged: true", rendered)
        self.assertIn("allowPrivilegeEscalation: true", rendered)
        self.assertIn("hostPath:\n            path: /sys/fs/cgroup", rendered)
        self.assertIn("mountPath: /sys/fs/cgroup", rendered)
        self.assertIn("mountPropagation: Bidirectional", rendered)
        self.assertIn("hostPID: true", rendered)
        self.assertIn("command:\n            - /usr/bin/nsenter", rendered)
        for argument in ("--cgroup=/proc/1/ns/cgroup", "--", "/app/api-server"):
            self.assertIn(f"- {argument}", rendered)
        self.assertIn("- -max-concurrency=2", rendered)

    def test_sandbox_concurrency_must_be_positive(self):
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                "--set",
                "sandbox.enabled=true",
                "--set",
                "sandbox.maxConcurrency=0",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("minimum: got 0, want 1", result.stderr)

    def test_production_profile_requires_an_isolated_runtime(self):
        digest = "sha256:" + ("a" * 64)
        rendered = self.render(
            "--values",
            str(CHART / "values-production.yaml"),
            "--set",
            "sandbox.enabled=true",
            "--set-string",
            f"sandbox.image.digest={digest}",
        )

        self.assertIn("runtimeClassName: kata-qemu", rendered)
        self.assertIn('coderushoj.io/sandbox-worker: "true"', rendered)
        self.assertIn("privileged: false", rendered)
        self.assertIn("readOnlyRootFilesystem: true", rendered)
        self.assertIn("runAsUser: 65532", rendered)
        self.assertIn("hostPID: false", rendered)
        self.assertIn(f"image: \"ghcr.io/coderushoj/croj-sandbox@{digest}\"", rendered)
        self.assertNotIn("hostPath:", rendered)

    def test_production_profile_rejects_a_mutable_image_reference(self):
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                "--values",
                str(CHART / "values-production.yaml"),
                "--set",
                "sandbox.enabled=true",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("sandbox.image.digest is required", result.stderr)

    def test_production_profile_is_disabled_by_default(self):
        rendered = self.render("--values", str(CHART / "values-production.yaml"))

        self.assertNotIn("name: croj-sandbox", rendered)

    def test_rejects_malformed_or_short_image_digests(self):
        for digest in ("sha256:abc", "sha512:" + ("a" * 64), "sha256:" + ("G" * 64)):
            with self.subTest(digest=digest):
                result = subprocess.run(
                    [
                        "helm",
                        "template",
                        "coderushoj",
                        str(CHART),
                        "--namespace",
                        "coderushoj",
                        "--values",
                        str(CHART / "values-production.yaml"),
                        "--set",
                        "sandbox.enabled=true",
                        "--set-string",
                        f"sandbox.image.digest={digest}",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("does not match pattern '^(|sha256:[0-9a-f]{64})$'", result.stderr)

    def test_rejects_a_service_name_that_breaks_judging_discovery(self):
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                "--set",
                "sandbox.enabled=true",
                "--set",
                "sandbox.service.name=renamed-sandbox",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("croj-sandbox", result.stderr)

    def test_rejects_reserved_selector_label_overrides(self):
        for label in ("app.kubernetes.io/name", "app.kubernetes.io/instance"):
            with self.subTest(label=label):
                escaped_label = label.replace(".", "\\.")
                result = subprocess.run(
                    [
                        "helm",
                        "template",
                        "coderushoj",
                        str(CHART),
                        "--namespace",
                        "coderushoj",
                        "--set",
                        "sandbox.enabled=true",
                        "--set-string",
                        f"sandbox.podLabels.{escaped_label}=override",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("reserved selector label", result.stderr)

    def test_sandbox_can_be_disabled_without_dangling_service(self):
        rendered = self.render("--set", "sandbox.enabled=false")

        self.assertNotIn("name: croj-sandbox", rendered)

    def test_discovery_rbac_is_namespace_scoped_and_read_only(self):
        rendered = self.render(
            "--set", "judgingServer.enabled=true",
            "--set", "judgingServer.existingSecret.name=coderushoj-application",
        )

        self.assertIn("kind: ServiceAccount\nmetadata:\n  name: coderushoj-judging-server", rendered)
        self.assertIn("kind: Role\nmetadata:\n  name: coderushoj-judging-server-endpointslices", rendered)
        self.assertIn("apiGroups:\n      - discovery.k8s.io", rendered)
        self.assertIn("resources:\n      - endpointslices", rendered)
        self.assertIn("verbs:\n      - list", rendered)
        self.assertNotIn("kind: ClusterRole", rendered)

    def test_values_schema_rejects_an_invalid_grpc_port(self):
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                "--set",
                "sandbox.enabled=true",
                "--set",
                "sandbox.service.port=0",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("minimum: got 0, want 1", result.stderr)


if __name__ == "__main__":
    unittest.main()
