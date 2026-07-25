import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/coderushoj"


class GatewayRenderTest(unittest.TestCase):
    def test_gateway_dependency_versions_match_envoy_release(self):
        versions = (ROOT / "config/versions.env").read_text()
        self.assertIn("GATEWAY_API_VERSION=v1.5.1", versions)
        self.assertIn(
            "ENVOY_GATEWAY_INSTALL_SHA256="
            "58a265a7cd515d2c782964a9f27ba20427259e1f4ab5ea015ec218ef3f737e08",
            versions,
        )

        installer = (ROOT / "scripts/install-gateway.sh").read_text()
        self.assertIn("releases/download/$ENVOY_GATEWAY_VERSION/install.yaml", installer)
        self.assertIn("curl -4", installer)
        self.assertIn("shasum -a 256", installer)

    def test_gateway_and_application_routes_render(self):
        self.assertTrue((CHART / "Chart.yaml").is_file(), "application chart is missing")
        result = subprocess.run(
            [
                "helm", "template", "coderushoj", str(CHART),
                "--namespace", "coderushoj", "--set", "applications.enabled=true",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        rendered = result.stdout
        self.assertIn("kind: GatewayClass", rendered)
        self.assertIn("apiVersion: gateway.networking.k8s.io/v1\nkind: Gateway", rendered)
        self.assertIn("kind: HTTPRoute", rendered)
        self.assertIn("coderushoj.local", rendered)
        for route in ("/api", "/docs", "/"):
            self.assertIn(f"value: {route}", rendered)

    def test_kind_gateway_uses_fixed_node_port(self):
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
                "--values",
                str(CHART / "values-kind.yaml"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        rendered = result.stdout
        self.assertIn("kind: EnvoyProxy", rendered)
        self.assertIn("type: NodePort", rendered)
        self.assertIn("nodePort: 30080", rendered)
        self.assertIn("externalTrafficPolicy: Cluster", rendered)
        self.assertIn("parametersRef:", rendered)

    def test_gateway_rejects_an_invalid_external_traffic_policy(self):
        result = subprocess.run(
            [
                "helm",
                "template",
                "coderushoj",
                str(CHART),
                "--namespace",
                "coderushoj",
                "--set",
                "gateway.envoyProxy.enabled=true",
                "--set",
                "gateway.envoyProxy.externalTrafficPolicy=Invalid",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("externalTrafficPolicy", result.stderr)

    def test_external_judge_route_exposes_versioned_api_and_health_only(self):
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
                "--set",
                "applications.enabled=true",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        judge_route = result.stdout.split("name: coderushoj-judge-api", 1)[1]
        for path in ("/api/v1", "/readyz", "/livez"):
            self.assertIn(f"value: {path}", judge_route)


if __name__ == "__main__":
    unittest.main()
