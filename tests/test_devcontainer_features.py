import json
import unittest
from unittest.mock import patch

from helpers.devcontainer_helpers import (
    generate_devcontainer_json,
    validate_devcontainer_json,
)
from helpers.jinja_helper import process_template
from schemas import DevContainerModel


FEATURE_ID = "ghcr.io/devcontainers/features/github-cli:1"


class FakeResponse:
    def dict(self, exclude_none=True):
        return {
            "name": "Python tools",
            "image": "mcr.microsoft.com/devcontainers/python:1-3.12-bookworm",
            "features": {FEATURE_ID: {}},
            "forwardPorts": [],
        }


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse()


class FakeInstructorClient:
    def __init__(self):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions()


class DevContainerFeatureIntegrationTests(unittest.TestCase):
    def test_response_model_exposes_features(self):
        schema = DevContainerModel.model_json_schema()
        model = DevContainerModel(
            name="Python tools",
            image="mcr.microsoft.com/devcontainers/python:1-3.12-bookworm",
            forwardPorts=[],
            customizations=None,
            settings=None,
            postCreateCommand=None,
        )

        self.assertIn("features", schema["properties"])
        self.assertEqual("object", schema["properties"]["features"]["type"])
        self.assertEqual({}, model.model_dump(exclude_none=True)["features"])

    def test_project_schema_accepts_a_versioned_feature(self):
        payload = {
            "name": "Python tools",
            "image": "mcr.microsoft.com/devcontainers/python:1-3.12-bookworm",
            "features": {FEATURE_ID: {}},
            "forwardPorts": [],
        }

        self.assertTrue(validate_devcontainer_json(json.dumps(payload)))

    @patch("helpers.devcontainer_helpers.validate_devcontainer_json", return_value=True)
    @patch(
        "helpers.devcontainer_helpers.truncate_context",
        side_effect=lambda value, **_: value,
    )
    @patch(
        "helpers.devcontainer_helpers.build_feature_catalog_context",
        return_value="<<FEATURE CATALOG>>",
    )
    def test_generation_feeds_catalog_to_prompt_and_serializes_features(
        self, build_catalog, _truncate, _validate
    ):
        client = FakeInstructorClient()

        result, source_url = generate_devcontainer_json(
            client,
            "https://github.com/acme/widgets",
            "requirements.txt\nPython: 1000 lines",
            max_retries=0,
        )

        build_catalog.assert_called_once_with("requirements.txt\nPython: 1000 lines")
        self.assertIsNone(source_url)
        self.assertEqual({FEATURE_ID: {}}, json.loads(result)["features"])

        call = client.chat.completions.calls[0]
        self.assertIs(DevContainerModel, call["response_model"])
        self.assertIn("<<FEATURE CATALOG>>", call["messages"][1]["content"])
        self.assertIn("untrusted data", call["messages"][0]["content"])

    def test_prompt_requires_evidence_and_versioned_feature_ids(self):
        prompt = process_template(
            "prompts/devcontainer.jinja",
            {
                "repo_url": "https://github.com/acme/widgets",
                "repo_context": "requirements.txt",
                "existing_devcontainer": None,
                "feature_catalog_context": "catalog marker",
            },
        )

        self.assertIn("catalog marker", prompt)
        self.assertIn("<namespace>/<feature-id>:<major-version>", prompt)
        self.assertIn("empty `features` object instead of inventing", prompt)
        self.assertIn('"features": {},', prompt)


if __name__ == "__main__":
    unittest.main()
