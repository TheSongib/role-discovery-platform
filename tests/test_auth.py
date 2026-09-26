import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import api
import auth


class AuthenticationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.auth_settings = patch.multiple(
            auth,
            AUTH_ENABLED=True,
            PUBLIC_BASE_URL="https://example.execute-api.us-east-1.amazonaws.com",
            COGNITO_REGION="us-east-1",
            COGNITO_USER_POOL_ID="us-east-1_example",
            COGNITO_CLIENT_ID="client-id",
            COGNITO_DOMAIN="https://role-discovery.auth.us-east-1.amazoncognito.com",
            COGNITO_ADMIN_GROUP="admins",
        )
        self.auth_settings.start()
        self.addCleanup(self.auth_settings.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def test_anonymous_viewer_can_read_but_cannot_request_hidden_jobs(self):
        with patch("api.query_jobs", return_value=[]) as query_jobs:
            response = self.client.get("/api/jobs?show_hidden=true&max_age_days=7")

        self.assertEqual(response.status_code, 200)
        query_jobs.assert_called_once_with(show_hidden=False, max_age_days=7)

    def test_job_response_includes_company_brand_color(self):
        job = {"id": "job-1", "company": "Coinbase", "title": "Engineer"}
        with patch("api.query_jobs", return_value=[job]):
            response = self.client.get("/api/jobs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["company_color"], "#0052FF")

    def test_every_state_changing_route_requires_admin_login(self):
        origin = "https://example.execute-api.us-east-1.amazonaws.com"
        requests = (
            ("post", "/api/scan", None),
            ("patch", "/api/jobs/job-1", {"hidden": True}),
            (
                "put",
                "/api/config/keywords",
                {"title_keywords": ["security"], "title_exclude_keywords": []},
            ),
        )
        for method, path, body in requests:
            with self.subTest(path=path):
                response = getattr(self.client, method)(
                    path,
                    json=body,
                    headers={"origin": origin},
                )
                self.assertEqual(response.status_code, 401)

    def test_admin_can_start_async_scan(self):
        claims = {
            "sub": "admin-user",
            "cognito:username": "admin",
            "cognito:groups": ["admins"],
        }
        with (
            patch("auth._decode_id_token", return_value=claims),
            patch("api._run_scan") as run_scan,
        ):
            response = self.client.post(
                "/api/scan",
                cookies={auth.SESSION_COOKIE: "signed-cognito-token"},
                headers={
                    "origin": "https://example.execute-api.us-east-1.amazonaws.com"
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "accepted")
        self.assertIn("accepted_at", response.json())
        run_scan.assert_called_once_with("manual")

    def test_admin_mutation_rejects_cross_origin_request(self):
        claims = {"sub": "admin-user", "cognito:groups": ["admins"]}
        with patch("auth._decode_id_token", return_value=claims):
            response = self.client.patch(
                "/api/jobs/job-1",
                json={"hidden": True},
                cookies={auth.SESSION_COOKIE: "signed-cognito-token"},
                headers={"origin": "https://attacker.example"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "Cross-origin administrative request rejected",
        )

    def test_non_admin_cognito_user_cannot_mutate(self):
        claims = {"sub": "viewer-user", "cognito:groups": ["viewers"]}
        with patch("auth._decode_id_token", return_value=claims):
            response = self.client.post(
                "/api/scan",
                cookies={auth.SESSION_COOKIE: "signed-cognito-token"},
                headers={
                    "origin": "https://example.execute-api.us-east-1.amazonaws.com"
                },
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "Administrator group membership required",
        )

    def test_origin_secret_blocks_direct_ec2_access(self):
        with (
            patch.object(api, "ORIGIN_VERIFY_SECRET", "gateway-only-secret"),
            patch("api.query_jobs", return_value=[]),
        ):
            blocked = self.client.get("/api/jobs")
            allowed = self.client.get(
                "/api/jobs",
                headers={"x-origin-verify": "gateway-only-secret"},
            )
            health = self.client.get("/api/health")

        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(allowed.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", allowed.headers["content-security-policy"])


class CognitoFlowTests(unittest.TestCase):
    def setUp(self):
        self.auth_settings = patch.multiple(
            auth,
            AUTH_ENABLED=True,
            PUBLIC_BASE_URL="https://example.execute-api.us-east-1.amazonaws.com",
            COGNITO_REGION="us-east-1",
            COGNITO_USER_POOL_ID="us-east-1_example",
            COGNITO_CLIENT_ID="client-id",
            COGNITO_DOMAIN="https://role-discovery.auth.us-east-1.amazoncognito.com",
            COGNITO_ADMIN_GROUP="admins",
        )
        self.auth_settings.start()
        self.addCleanup(self.auth_settings.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def test_login_uses_authorization_code_pkce_and_secure_cookies(self):
        response = self.client.get("/api/auth/login", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.headers["location"]).query)
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["client_id"], ["client-id"])
        self.assertNotIn("client_secret", query)
        cookies = response.headers.get_list("set-cookie")
        self.assertEqual(len(cookies), 3)
        for cookie in cookies:
            self.assertIn("HttpOnly", cookie)
            self.assertIn("Secure", cookie)
            self.assertIn("SameSite=lax", cookie)

    def test_callback_sets_httponly_session_for_admin_group(self):
        token_response = Mock(ok=True)
        token_response.json.return_value = {"id_token": "verified-id-token"}
        claims = {
            "sub": "admin-user",
            "nonce": "expected-nonce",
            "exp": int(time.time()) + 900,
            "cognito:groups": ["admins"],
        }
        with (
            patch("auth.requests.post", return_value=token_response),
            patch("auth._decode_id_token", return_value=claims),
        ):
            response = self.client.get(
                "/api/auth/callback?code=authorization-code&state=expected-state",
                cookies={
                    auth.STATE_COOKIE: "expected-state",
                    auth.VERIFIER_COOKIE: "pkce-verifier",
                    auth.NONCE_COOKIE: "expected-nonce",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        session_cookie = next(
            cookie
            for cookie in response.headers.get_list("set-cookie")
            if cookie.startswith(f"{auth.SESSION_COOKIE}=")
        )
        self.assertIn("verified-id-token", session_cookie)
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("Secure", session_cookie)
        token_response.json.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
