import base64
import sys
import types
import unittest
from unittest.mock import patch

import requests

supabase_stub = types.ModuleType("supabase_client")
supabase_stub.supabase = object()
with patch.dict(sys.modules, {"supabase_client": supabase_stub}):
    from helpers import github_helpers

fetch_port_evidence_context = github_helpers.fetch_port_evidence_context
fetch_repo_context = github_helpers.fetch_repo_context


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def encoded_blob(content):
    return {
        "encoding": "base64",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }


class GitHubPortContextTests(unittest.TestCase):
    def test_repository_context_includes_port_evidence_before_languages(self):
        repository_url = "https://api.github.com/repos/acme/widgets/contents"
        responses = {
            f"{repository_url}/.devcontainer.json": FakeResponse({}, status_code=404),
            f"{repository_url}/.devcontainer": FakeResponse({}, status_code=404),
            repository_url: FakeResponse(
                [
                    {
                        "name": "README.md",
                        "type": "file",
                        "download_url": "https://raw.example/readme",
                    }
                ]
            ),
            "https://raw.example/readme": FakeResponse({}, text="Run on port 3000"),
            "https://api.github.com/repos/acme/widgets/languages": FakeResponse(
                {"Python": 100}
            ),
        }

        with patch.object(
            github_helpers,
            "fetch_port_evidence_context",
            return_value="<<SECTION: Detected Forwarded Port Evidence >>\n- Port 3000",
        ) as port_scan, patch.object(
            github_helpers, "count_tokens", side_effect=lambda text: len(text)
        ), patch.object(
            github_helpers.requests,
            "get",
            side_effect=lambda url, **kwargs: responses[url],
        ):
            context, existing, existing_url = fetch_repo_context(
                "https://github.com/acme/widgets"
            )

        self.assertIsNone(existing)
        self.assertIsNone(existing_url)
        self.assertLess(
            context.index("Detected Forwarded Port Evidence"),
            context.index("Repository Languages"),
        )
        port_scan.assert_called_once()
        self.assertEqual(port_scan.call_args.args[:2], ("acme", "widgets"))

    def test_recursively_scans_nested_relevant_files_with_sources(self):
        repository_url = "https://api.github.com/repos/acme/widgets"
        tree_url = f"{repository_url}/git/trees/trunk"
        responses = {
            repository_url: FakeResponse({"default_branch": "trunk"}),
            tree_url: FakeResponse(
                {
                    "truncated": False,
                    "tree": [
                        {
                            "path": "docs/setup/README.md",
                            "type": "blob",
                            "size": 40,
                            "url": "https://api.github.com/blobs/readme",
                        },
                        {
                            "path": "services/api/config.py",
                            "type": "blob",
                            "size": 40,
                            "url": "https://api.github.com/blobs/api",
                        },
                        {
                            "path": "node_modules/pkg/server.js",
                            "type": "blob",
                            "size": 40,
                            "url": "https://api.github.com/blobs/dependency",
                        },
                        {
                            "path": "assets/logo.png",
                            "type": "blob",
                            "size": 40,
                            "url": "https://api.github.com/blobs/logo",
                        },
                    ],
                }
            ),
            "https://api.github.com/blobs/readme": FakeResponse(
                encoded_blob("Browse to http://localhost:3000\n")
            ),
            "https://api.github.com/blobs/api": FakeResponse(
                encoded_blob("API_PORT=8080\n")
            ),
        }
        requested_urls = []

        def fake_get(url, **kwargs):
            requested_urls.append((url, kwargs))
            return responses[url]

        with patch.object(github_helpers.requests, "get", side_effect=fake_get):
            section = fetch_port_evidence_context(
                "acme", "widgets", {"Authorization": "token"}
            )

        self.assertIn("Port 3000", section)
        self.assertIn("docs/setup/README.md:1", section)
        self.assertIn("Port 8080", section)
        self.assertIn("services/api/config.py:1", section)
        self.assertNotIn("dependency", [url for url, _ in requested_urls])
        tree_request = next(kwargs for url, kwargs in requested_urls if url == tree_url)
        self.assertEqual(tree_request["params"], {"recursive": "1"})

    def test_reports_scan_limits_without_failing_generation(self):
        repository_url = "https://api.github.com/repos/acme/large"
        tree_url = f"{repository_url}/git/trees/main"

        def fake_get(url, **kwargs):
            if url == repository_url:
                return FakeResponse({"default_branch": "main"})
            if url == tree_url:
                return FakeResponse(
                    {
                        "truncated": True,
                        "tree": [
                            {
                                "path": "README.md",
                                "type": "blob",
                                "size": 20,
                                "url": "https://api.github.com/blobs/readme",
                            }
                        ],
                    }
                )
            return FakeResponse(encoded_blob("port 4000\n"))

        with patch.object(github_helpers.requests, "get", side_effect=fake_get):
            section = fetch_port_evidence_context("acme", "large", {})

        self.assertIn("Port 4000", section)
        self.assertIn("safety scan limit was reached", section)


if __name__ == "__main__":
    unittest.main()
