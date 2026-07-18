import pathlib
import re
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/coderushoj-infra"


class InfrastructureRenderTest(unittest.TestCase):
    def render(self, *extra_args):
        self.assertTrue((CHART / "Chart.yaml").is_file(), "infrastructure chart is missing")
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj-infra",
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

    def test_renders_pinned_stateful_dependencies(self):
        rendered = self.render()
        for image in (
            "mysql:8.4.10",
            "redis:8.6.2-alpine",
            "apache/rocketmq:5.5.0",
            "chrislusf/seaweedfs:4.39",
        ):
            self.assertIn(f"image: {image}", rendered)
        self.assertNotRegex(rendered, r"image:\s+\S+:latest(?:\s|$)")

        self.assertGreaterEqual(rendered.count("kind: StatefulSet"), 4)
        self.assertIn("kind: Deployment", rendered)
        self.assertGreaterEqual(rendered.count("volumeClaimTemplates:"), 4)
        self.assertGreaterEqual(rendered.count("readinessProbe:"), 5)
        self.assertGreaterEqual(rendered.count("resources:"), 5)
        self.assertIn("-Xms512m -Xmx512m", rendered)
        self.assertIn("-XX:MaxDirectMemorySize=256m", rendered)

    def test_security_and_secret_contracts(self):
        rendered = self.render()
        self.assertGreaterEqual(rendered.count("allowPrivilegeEscalation: false"), 5)
        self.assertGreaterEqual(rendered.count("runAsNonRoot: true"), 5)
        self.assertGreaterEqual(rendered.count("seccompProfile:"), 5)
        self.assertIn("kind: NetworkPolicy", rendered)
        self.assertIn("policyTypes:\n    - Ingress\n    - Egress", rendered)

        self.assertNotIn("password: coderushoj", rendered.lower())
        for key in ("mysql-root-password", "redis-password", "s3-access-key", "s3-secret-key"):
            self.assertIn(f"key: {key}", rendered)

    def test_local_memory_requests_fit_workstation_budget(self):
        rendered = self.render()
        requests = re.findall(r"requests:\n\s+cpu: [^\n]+\n\s+memory: (\d+)(Mi|Gi)", rendered)
        self.assertTrue(requests, "no workload memory requests were rendered")
        total_mib = sum(int(value) * (1024 if unit == "Gi" else 1) for value, unit in requests)
        self.assertLessEqual(total_mib, 5632)

    def test_production_profile_keeps_secrets_external(self):
        rendered = self.render("--values", str(CHART / "values-production.yaml"))
        self.assertIn("coderushoj-production-secrets", rendered)
        self.assertNotIn("kind: Secret", rendered)


if __name__ == "__main__":
    unittest.main()
