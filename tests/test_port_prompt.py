import unittest

from helpers.openai_helpers import build_devcontainer_messages
from helpers.jinja_helper import process_template


class PortPromptTests(unittest.TestCase):
    def test_system_message_rejects_unsupported_default_ports(self):
        messages = build_devcontainer_messages("rendered prompt")

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("explicit repository", messages[0]["content"])
        self.assertIn("Never default to port 8000", messages[0]["content"])
        self.assertEqual(messages[1], {"role": "user", "content": "rendered prompt"})

    def test_template_prioritizes_evidence_and_allows_no_forwarded_ports(self):
        prompt = process_template(
            "prompts/devcontainer.jinja",
            {
                "repo_url": "https://github.com/acme/widgets",
                "repo_context": "<<SECTION: Detected Forwarded Port Evidence >>\n- Port 3000",
                "existing_devcontainer": None,
            },
        )

        self.assertIn("Prefer executable configuration and run commands", prompt)
        self.assertIn("leave `forwardPorts` empty or null", prompt)
        self.assertIn("Never default to port 8000", prompt)


if __name__ == "__main__":
    unittest.main()
