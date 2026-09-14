import importlib
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient


def load_main_module():
    """Import the app without creating a real Supabase client."""
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    supabase_client = types.ModuleType("supabase_client")
    supabase_client.supabase = object()
    required_variables = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "MODEL",
        "GITHUB_TOKEN",
        "SUPABASE_URL",
        "SUPABASE_KEY",
    ]

    previous_supabase_client = sys.modules.get("supabase_client")
    sys.modules["supabase_client"] = supabase_client

    sys.modules.pop("main", None)
    try:
        with patch.dict(os.environ, {name: "" for name in required_variables}):
            return importlib.import_module("main")
    finally:
        if previous_supabase_client is None:
            sys.modules.pop("supabase_client", None)
        else:
            sys.modules["supabase_client"] = previous_supabase_client


class DevcontainerRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = load_main_module()
        cls.client = TestClient(cls.main.app)

    def test_returns_devcontainer_as_plain_text(self):
        repo_url = "https://github.com/daytonaio/daytona"
        resolved = {
            "devcontainer_json": '{"name": "Daytona"}',
            "repo_url": repo_url,
            "source": "database",
        }

        with patch.object(
            self.main, "resolve_devcontainer", return_value=resolved
        ) as resolve:
            response = self.client.get("/devcontainer", params={"repo_url": repo_url})

        resolve.assert_called_once_with(repo_url, regenerate=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'{"name": "Daytona"}')
        self.assertTrue(response.headers["content-type"].startswith("text/plain"))
        self.assertEqual(
            response.headers["content-disposition"],
            'inline; filename="devcontainer.json"',
        )

    def test_html_form_uses_the_same_resolver(self):
        repo_url = "https://github.com/daytonaio/daytona"
        resolved = {
            "devcontainer_json": '{"name": "Daytona"}',
            "repo_url": repo_url,
            "source": "database",
        }

        with patch.object(
            self.main, "resolve_devcontainer", return_value=resolved
        ) as resolve:
            response = self.client.post("/generate", data={"repo_url": repo_url})

        resolve.assert_called_once_with(repo_url, regenerate=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn("found in database", response.text)
        self.assertIn("Daytona", response.text)

    def test_rejects_invalid_urls_before_database_or_github_calls(self):
        with (
            patch.object(self.main, "is_valid_github_url", return_value=False),
            patch.object(self.main, "check_url_exists") as database_lookup,
            patch.object(self.main, "fetch_repo_context") as repo_fetch,
        ):
            with self.assertRaises(self.main.InvalidRepositoryUrl):
                self.main.resolve_devcontainer("not-a-url")

        database_lookup.assert_not_called()
        repo_fetch.assert_not_called()

    def test_returns_bad_request_for_invalid_repository_url(self):
        with patch.object(
            self.main,
            "resolve_devcontainer",
            side_effect=self.main.InvalidRepositoryUrl("Invalid GitHub repository URL"),
        ):
            response = self.client.get(
                "/devcontainer",
                params={"repo_url": "not-a-url"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b"Invalid GitHub repository URL")

    def test_hides_internal_errors_from_script_clients(self):
        with patch.object(
            self.main,
            "resolve_devcontainer",
            side_effect=RuntimeError("secret backend detail"),
        ):
            response = self.client.get(
                "/devcontainer",
                params={"repo_url": "https://github.com/daytonaio/daytona"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content, b"Unable to generate devcontainer.json")
        self.assertNotIn(b"secret backend detail", response.content)


if __name__ == "__main__":
    unittest.main()
