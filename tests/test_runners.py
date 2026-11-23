"""Dual-runner tests for backend/app.py.

The same backend serves as the local runner (default, no auth)
and as the cloud runner (SV_MODE=cloud, SV_API_TOKEN set). These
tests load the app module fresh under different environments and
check the contract each mode promises:

  local   health reports mode "local", no auth anywhere
  cloud   health stays open and reports mode "cloud" with
          auth_required; job endpoints answer 401 without the
          bearer token, pass the gate with it, and still 401 on
          a wrong token; CORS answers for configured origins

Skips cleanly when FastAPI is not installed, like test_app.py.
"""

import importlib.util
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "backend"))

try:
    import fastapi  # noqa: F401
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:
    HAVE_FASTAPI = False

APP_PATH = os.path.join(os.path.dirname(__file__), "..", "backend",
                        "app.py")
_TMP = tempfile.mkdtemp()


def load_app(name, env):
    """Import backend/app.py under a fresh module name with env."""
    keys = ["CSS_JOBS_DIR", "SV_MODE", "SV_API_TOKEN",
            "SV_CORS_ORIGINS"]
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["CSS_JOBS_DIR"] = os.path.join(_TMP, name, "jobs")
    for k in keys[1:]:
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(name, APP_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k in keys:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class LocalModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(load_app("app_local", {}).app)

    def test_health_reports_local_without_auth(self):
        body = self.client.get("/api/health").json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["app"], "SculptViseme")
        self.assertEqual(body["mode"], "local")
        self.assertFalse(body["auth_required"])

    def test_job_endpoints_open_without_token(self):
        # 404 (no such job) proves the request passed any gate.
        res = self.client.get("/api/jobs/nope")
        self.assertEqual(res.status_code, 404)


@unittest.skipUnless(HAVE_FASTAPI, "fastapi not installed")
class CloudModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mod = load_app("app_cloud", {
            "SV_MODE": "cloud",
            "SV_API_TOKEN": "test-secret",
            "SV_CORS_ORIGINS": "https://studio.example",
        })
        cls.client = TestClient(mod.app, raise_server_exceptions=False)

    def test_health_open_and_reports_cloud(self):
        body = self.client.get("/api/health").json()
        self.assertEqual(body["mode"], "cloud")
        self.assertTrue(body["auth_required"])

    def test_job_endpoint_requires_token(self):
        res = self.client.get("/api/jobs/nope")
        self.assertEqual(res.status_code, 401)

    def test_wrong_token_rejected(self):
        res = self.client.get(
            "/api/jobs/nope",
            headers={"Authorization": "Bearer wrong"})
        self.assertEqual(res.status_code, 401)

    def test_right_token_passes_gate(self):
        res = self.client.get(
            "/api/jobs/nope",
            headers={"Authorization": "Bearer test-secret"})
        self.assertEqual(res.status_code, 404)

    def test_401_carries_cors_header_for_configured_origin(self):
        # Regression: the token gate answers before the CORS
        # middleware, so its 401 must carry the allow-origin
        # header itself, or a browser reads it as a network
        # failure instead of an auth rejection.
        res = self.client.get(
            "/api/jobs/nope", headers={"Origin": "https://studio.example"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(
            res.headers.get("access-control-allow-origin"),
            "https://studio.example")

    def test_cors_allows_configured_origin(self):
        res = self.client.get(
            "/api/health", headers={"Origin": "https://studio.example"})
        self.assertEqual(
            res.headers.get("access-control-allow-origin"),
            "https://studio.example")

    def test_cors_preflight_for_authorized_post(self):
        res = self.client.options(
            "/api/bundles",
            headers={
                "Origin": "https://studio.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.headers.get("access-control-allow-origin"),
            "https://studio.example")


if __name__ == "__main__":
    unittest.main()
