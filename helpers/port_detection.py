"""Detect evidence-backed application ports in repository text files.

The detector intentionally looks for port-shaped values only when they appear in
network-related syntax or language. This keeps unrelated version numbers, years,
and dependency hashes out of the LLM context.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Sequence


DOCUMENTATION_SUFFIXES = {".adoc", ".html", ".md", ".mdx", ".rst", ".txt"}
CONFIGURATION_SUFFIXES = {
    ".cfg",
    ".conf",
    ".ini",
    ".json",
    ".kts",
    ".properties",
    ".tf",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
}
SOURCE_SUFFIXES = {
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".ts",
    ".tsx",
}

SKIPPED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
    "venv",
}
TEST_DIRECTORY_NAMES = {"fixtures", "spec", "specs", "test", "tests"}
LOCKFILE_NAMES = {
    "cargo.lock",
    "composer.lock",
    "go.sum",
    "package-lock.json",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "yarn.lock",
}
HIGH_SIGNAL_NAMES = {
    ".env",
    ".env.example",
    ".env.local",
    "app.py",
    "contributing.md",
    "devcontainer.json",
    "docker-compose.yaml",
    "docker-compose.yml",
    "makefile",
    "manage.py",
    "package.json",
    "procfile",
    "pyproject.toml",
    "readme.md",
    "server.js",
    "server.py",
    "server.ts",
}

MAX_SNIPPET_LENGTH = 180
MAX_REFERENCES_PER_PORT = 4
MAX_UNIQUE_PORTS = 100


@dataclass(frozen=True)
class PortEvidence:
    """A port number and the repository line that supports it."""

    port: int
    path: str
    line_number: int
    snippet: str


_DIRECT_PATTERNS = (
    re.compile(
        r"\b(?:https?|wss?)://[^\s/:]+:(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|\[?::1?\]?)"
        r"\s*:\s*(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:--port(?:=|\s+)|-p\s+)(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:[A-Z][A-Z0-9_]*_PORT|PORT)\s*[:=]\s*[\"']?(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:appPort|containerPort|hostPort|targetPort|server\.port|http\.port|https\.port)"
        r"\s*[:=]\s*[\"']?(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:runserver|serve)\s+(?:[\w.\-]+:)?(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:listen|bind)\s*\(\s*[\"']?(?::|0\.0\.0\.0:)?(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bListenAndServe\s*\(\s*[\"']:(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bports?\s+(?:is|are|at|on|to)?\s*[:=]?\s*[\"']?(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\$\{[A-Z0-9_]*PORT[^}]*:-\s*(?P<port>\d{1,5})\}",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:process\.env\.[A-Z0-9_]*PORT|ENV\.fetch\([\"']PORT[\"']\))"
        r"[^#\n]{0,40}?(?:\|\||,|\{)\s*(?P<port>\d{1,5})\b",
        re.IGNORECASE,
    ),
)

_DIRECTIVE_PATTERN = re.compile(
    r"\b(?:EXPOSE|forwardPorts?)\b(?P<values>[^#\n]{0,160})",
    re.IGNORECASE,
)
_PORT_LIST_PATTERN = re.compile(
    r"\b(?:forwarded\s+ports?|ports?)\b\s*(?:are|include|:|=)?"
    r"(?P<values>[^#\n]{0,120})",
    re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(r"(?<![\d.])(?P<port>\d{1,5})(?![\d.])")
_DOCKER_MAPPING_PATTERN = re.compile(
    r"(?<!\d)[\"']?(?P<host>\d{1,5})\s*:\s*"
    r"(?P<container>\d{1,5})(?:/(?:tcp|udp))?[\"']?(?!\d)",
    re.IGNORECASE,
)
_PORT_ATTRIBUTE_PATTERN = re.compile(r"[\"'](?P<port>\d{1,5})[\"']\s*:\s*\{")
_COMPOSE_LONG_PORT_PATTERN = re.compile(
    r"\b(?:published|target)\s*:\s*[\"']?(?P<port>\d{1,5})\b",
    re.IGNORECASE,
)
_NEGATION_PATTERN = re.compile(
    r"\b(?:avoid|do\s+not|don't|never|no|not|without)\b", re.IGNORECASE
)


def is_relevant_port_file(path: str) -> bool:
    """Return whether a repository file can reasonably contain port evidence."""

    normalized = path.strip("/")
    if not normalized:
        return False

    pure_path = PurePosixPath(normalized)
    lowered_parts = {part.lower() for part in pure_path.parts[:-1]}
    if lowered_parts & SKIPPED_DIRECTORIES:
        return False

    name = pure_path.name.lower()
    if name in LOCKFILE_NAMES or name.endswith((".min.js", ".map")):
        return False
    if name in HIGH_SIGNAL_NAMES or name.startswith(
        (".env.", "dockerfile", "compose.")
    ):
        return True

    suffix = pure_path.suffix.lower()
    return suffix in DOCUMENTATION_SUFFIXES | CONFIGURATION_SUFFIXES | SOURCE_SUFFIXES


def port_file_priority(path: str) -> tuple[int, str]:
    """Sort high-signal manifests and documentation before general source files."""

    pure_path = PurePosixPath(path)
    name = pure_path.name.lower()
    suffix = pure_path.suffix.lower()
    if {part.lower() for part in pure_path.parts[:-1]} & TEST_DIRECTORY_NAMES:
        priority = 3
    elif name in HIGH_SIGNAL_NAMES or name.startswith(
        (".env.", "dockerfile", "compose.")
    ):
        priority = 0
    elif suffix in DOCUMENTATION_SUFFIXES | CONFIGURATION_SUFFIXES:
        priority = 1
    else:
        priority = 2
    return priority, path.lower()


def _valid_port(value: str) -> int | None:
    port = int(value)
    return port if 1 <= port <= 65535 else None


def _snippet(line: str) -> str:
    compact = " ".join(line.strip().split())
    if len(compact) <= MAX_SNIPPET_LENGTH:
        return compact
    return compact[: MAX_SNIPPET_LENGTH - 1].rstrip() + "…"


def _only_negated_occurrences(line: str, port: int) -> bool:
    """Return whether every mention of ``port`` is in a negative clause."""

    occurrences = list(re.finditer(rf"(?<!\d){port}(?!\d)", line))
    if not occurrences:
        return False

    for occurrence in occurrences:
        prefix = line[max(0, occurrence.start() - 100) : occurrence.start()]
        clause = re.split(r"[.;]", prefix)[-1]
        if not _NEGATION_PATTERN.search(clause):
            return False
    return True


def extract_port_evidence(path: str, content: str) -> list[PortEvidence]:
    """Extract port numbers supported by explicit networking context."""

    evidence: dict[tuple[int, int], PortEvidence] = {}
    compose_file = "compose" in PurePosixPath(path).name.lower()
    in_port_attributes = False
    port_attributes_depth = 0

    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue

        starts_port_attributes = "portsattributes" in line.lower()
        if starts_port_attributes:
            in_port_attributes = True
            port_attributes_depth = 0

        ports: set[int] = set()
        for pattern in _DIRECT_PATTERNS:
            for match in pattern.finditer(line):
                port = _valid_port(match.group("port"))
                if port is not None:
                    ports.add(port)

        for match in _DIRECTIVE_PATTERN.finditer(line):
            for number in _NUMBER_PATTERN.finditer(match.group("values")):
                port = _valid_port(number.group("port"))
                if port is not None:
                    ports.add(port)

        for match in _PORT_LIST_PATTERN.finditer(line):
            for number in _NUMBER_PATTERN.finditer(match.group("values")):
                port = _valid_port(number.group("port"))
                if port is not None:
                    ports.add(port)

        mapping_context = compose_file or bool(
            re.search(r"(?:\bports?\b|(?:^|\s)-p(?:\s|=))", line, re.IGNORECASE)
        )
        mapping_context = mapping_context or bool(
            re.match(r"^\s*-\s*[\"']?\d{1,5}\s*:\s*\d{1,5}", line)
        )
        if mapping_context:
            for match in _DOCKER_MAPPING_PATTERN.finditer(line):
                for group in ("host", "container"):
                    port = _valid_port(match.group(group))
                    if port is not None:
                        ports.add(port)

        if compose_file:
            for match in _COMPOSE_LONG_PORT_PATTERN.finditer(line):
                port = _valid_port(match.group("port"))
                if port is not None:
                    ports.add(port)

        if in_port_attributes:
            for match in _PORT_ATTRIBUTE_PATTERN.finditer(line):
                port = _valid_port(match.group("port"))
                if port is not None:
                    ports.add(port)

        if in_port_attributes:
            port_attributes_depth += line.count("{") - line.count("}")
            if port_attributes_depth <= 0 and ("{" in line or "}" in line):
                in_port_attributes = False

        for port in (
            port for port in ports if not _only_negated_occurrences(line, port)
        ):
            evidence[(port, line_number)] = PortEvidence(
                port=port,
                path=path,
                line_number=line_number,
                snippet=_snippet(line),
            )

    return sorted(
        evidence.values(), key=lambda item: (item.port, item.line_number, item.path)
    )


def format_port_evidence(
    evidence: Iterable[PortEvidence],
    *,
    scanned_files: int,
    scan_truncated: bool = False,
) -> str:
    """Build a bounded, source-attributed prompt section for the LLM."""

    grouped: dict[int, list[PortEvidence]] = defaultdict(list)
    for item in evidence:
        grouped[item.port].append(item)

    lines = [
        "<<SECTION: Detected Forwarded Port Evidence >>",
        (
            f"Scanned {scanned_files} recursively discovered documentation, configuration, "
            "and relevant source files."
        ),
    ]
    if scan_truncated:
        lines.append(
            "The safety scan limit was reached; use the evidence below together with the rest "
            "of the repository context."
        )

    if not grouped:
        lines.append(
            "No evidence-backed ports were detected. Do not default to port 8000 or invent a port."
        )
    else:
        lines.append(
            "Candidate ports are listed with their sources. Forward only developer-facing services "
            "that the repository actually runs."
        )
        ranked_ports = sorted(
            grouped,
            key=lambda port: (
                min(port_file_priority(item.path)[0] for item in grouped[port]),
                -len(grouped[port]),
                port,
            ),
        )
        selected_ports = ranked_ports[:MAX_UNIQUE_PORTS]
        for port in sorted(selected_ports):
            references = sorted(
                grouped[port],
                key=lambda item: (port_file_priority(item.path), item.line_number),
            )
            lines.append(f"- Port {port}")
            for item in references[:MAX_REFERENCES_PER_PORT]:
                lines.append(f"  - {item.path}:{item.line_number}: {item.snippet}")
            remaining = len(references) - MAX_REFERENCES_PER_PORT
            if remaining > 0:
                lines.append(f"  - {remaining} additional reference(s) omitted")
        omitted_ports = len(grouped) - len(selected_ports)
        if omitted_ports > 0:
            lines.append(
                f"- {omitted_ports} lower-priority candidate port(s) omitted to bound prompt size"
            )

    lines.append("<<END_SECTION: Detected Forwarded Port Evidence >>")
    return "\n".join(lines)


def scan_port_files(files: Sequence[tuple[str, str]]) -> list[PortEvidence]:
    """Scan ``(path, content)`` pairs and return stable, de-duplicated evidence."""

    evidence: dict[tuple[int, str, int], PortEvidence] = {}
    for path, content in files:
        for item in extract_port_evidence(path, content):
            evidence[(item.port, item.path, item.line_number)] = item
    return sorted(
        evidence.values(), key=lambda item: (item.port, item.path, item.line_number)
    )
