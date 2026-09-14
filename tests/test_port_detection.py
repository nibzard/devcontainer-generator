import unittest

from helpers.port_detection import (
    extract_port_evidence,
    format_port_evidence,
    is_relevant_port_file,
    port_file_priority,
    scan_port_files,
)


class PortFileSelectionTests(unittest.TestCase):
    def test_selects_documentation_configuration_and_source_files(self):
        selected = [
            "README.md",
            "docs/setup/CONTRIBUTING.MD",
            "deploy/docker-compose.yml",
            "services/api/.env.example",
            "src/server.ts",
        ]
        for path in selected:
            with self.subTest(path=path):
                self.assertTrue(is_relevant_port_file(path))

    def test_skips_generated_dependencies_and_lockfiles(self):
        skipped = [
            "node_modules/pkg/index.js",
            "vendor/service/config.yml",
            "dist/server.js",
            "package-lock.json",
            "src/client.min.js",
            "src/client.js.map",
            "assets/logo.png",
        ]
        for path in skipped:
            with self.subTest(path=path):
                self.assertFalse(is_relevant_port_file(path))

    def test_prioritizes_high_signal_files(self):
        paths = [
            "tests/server.py",
            "src/server.py",
            "config/app.toml",
            "README.md",
            "Dockerfile.dev",
        ]
        self.assertEqual(
            sorted(paths, key=port_file_priority),
            [
                "Dockerfile.dev",
                "README.md",
                "src/server.py",
                "config/app.toml",
                "tests/server.py",
            ],
        )


class PortExtractionTests(unittest.TestCase):
    def test_extracts_common_port_forms_and_rejects_unrelated_numbers(self):
        content = """
        Project release 2024 uses Python 3.12.
        Open http://localhost:3000 after running `npm start`.
        uvicorn api:app --host 0.0.0.0 --port 8080
        API_PORT=4100
        server.port = 9090
        app.listen(5050)
        PORT=${PORT:-7000}
        const listenPort = process.env.PORT || 7001;
        http.ListenAndServe(":6060", handler)
        """

        evidence = extract_port_evidence("README.md", content)

        self.assertEqual(
            {item.port for item in evidence},
            {3000, 4100, 5050, 6060, 7000, 7001, 8080, 9090},
        )
        self.assertNotIn(2024, {item.port for item in evidence})

    def test_ignores_ports_mentioned_only_as_negative_examples(self):
        evidence = extract_port_evidence(
            "README.md",
            "Never default to port 8000; use port 3000 for the web app.\n",
        )
        self.assertEqual({item.port for item in evidence}, {3000})

    def test_extracts_directives_lists_and_compose_mappings(self):
        files = [
            ("Dockerfile", "EXPOSE 8000 8001/tcp\n"),
            (".devcontainer/devcontainer.json", '"forwardPorts": [3000, 9229]\n'),
            (
                ".devcontainer/devcontainer.json",
                '"portsAttributes": {\n  "6006": {}\n}\n',
            ),
            ("deploy/docker-compose.yml", '  - "5433:5432"\n'),
            (
                "deploy/compose.yaml",
                "  target: 80\n  published: 8081\n",
            ),
            ("README.md", "docker run -p 8088:80 acme/widgets\n"),
            ("README.md", "Development ports: 5173, 5174 and 65536\n"),
        ]

        evidence = scan_port_files(files)

        self.assertEqual(
            {item.port for item in evidence},
            {
                80,
                3000,
                5173,
                5174,
                5432,
                5433,
                6006,
                8000,
                8001,
                8081,
                8088,
                9229,
            },
        )

    def test_deduplicates_a_port_on_the_same_source_line(self):
        evidence = extract_port_evidence(
            "README.md",
            "The app on port 3000 is at http://localhost:3000.\n",
        )
        self.assertEqual(len(evidence), 1)

    def test_formats_source_attributed_evidence(self):
        evidence = scan_port_files(
            [
                ("README.md", "Open http://localhost:3000\n"),
                ("src/server.js", "app.listen(3000)\n"),
            ]
        )

        section = format_port_evidence(evidence, scanned_files=2)

        self.assertIn("Port 3000", section)
        self.assertIn("README.md:1", section)
        self.assertIn("src/server.js:1", section)
        self.assertIn("Scanned 2", section)

    def test_empty_evidence_explicitly_forbids_the_8000_fallback(self):
        section = format_port_evidence([], scanned_files=3)
        self.assertIn("No evidence-backed ports", section)
        self.assertIn("Do not default to port 8000", section)


if __name__ == "__main__":
    unittest.main()
