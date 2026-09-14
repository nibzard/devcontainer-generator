import base64
import binascii
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests

from helpers.token_helpers import count_tokens
from helpers.port_detection import (
    extract_port_evidence,
    format_port_evidence,
    is_relevant_port_file,
    port_file_priority,
)
from models import DevContainer
from supabase_client import supabase


PORT_SCAN_MAX_FILES = 75
PORT_SCAN_MAX_FILE_BYTES = 256 * 1024
PORT_SCAN_MAX_TOTAL_BYTES = 2 * 1024 * 1024
PORT_SCAN_MAX_WORKERS = 8
GITHUB_REQUEST_TIMEOUT_SECONDS = 5


def is_valid_github_url(url):
    pattern = r"^https?://github\.com/[\w-]+/[\w.-]+/?$"
    return re.match(pattern, url) is not None


def _fetch_port_scan_file(item, headers, max_file_bytes):
    """Fetch and decode one text blob, returning ``None`` when it is unusable."""

    try:
        blob_response = requests.get(
            item["url"],
            headers=headers,
            timeout=GITHUB_REQUEST_TIMEOUT_SECONDS,
        )
        blob_response.raise_for_status()
        blob_payload = blob_response.json()
        if blob_payload.get("encoding") != "base64":
            return None

        raw_content = base64.b64decode(blob_payload.get("content", ""))
        if len(raw_content) > max_file_bytes:
            return None
        return item["path"], raw_content.decode("utf-8")
    except (requests.RequestException, binascii.Error, UnicodeDecodeError, ValueError) as error:
        logging.warning("Skipping port scan for %s: %s", item["path"], error)
        return None


def fetch_port_evidence_context(
    owner,
    repo,
    headers,
    max_files=PORT_SCAN_MAX_FILES,
    max_file_bytes=PORT_SCAN_MAX_FILE_BYTES,
    max_total_bytes=PORT_SCAN_MAX_TOTAL_BYTES,
):
    """Recursively scan relevant repository files using the Git Trees API.

    Port discovery is deliberately best-effort. A temporary GitHub API failure
    should not prevent the generator from using the repository context it can
    still retrieve.
    """

    scanned_files = 0
    evidence = []
    scan_truncated = False

    try:
        repository_api_url = f"https://api.github.com/repos/{owner}/{repo}"
        repository_response = requests.get(
            repository_api_url,
            headers=headers,
            timeout=GITHUB_REQUEST_TIMEOUT_SECONDS,
        )
        repository_response.raise_for_status()
        default_branch = repository_response.json()["default_branch"]

        encoded_default_branch = quote(default_branch, safe="")
        tree_api_url = f"{repository_api_url}/git/trees/{encoded_default_branch}"
        tree_response = requests.get(
            tree_api_url,
            headers=headers,
            params={"recursive": "1"},
            timeout=GITHUB_REQUEST_TIMEOUT_SECONDS,
        )
        tree_response.raise_for_status()
        tree_payload = tree_response.json()

        entries = [
            item
            for item in tree_payload.get("tree", [])
            if item.get("type") == "blob"
            and item.get("url")
            and is_relevant_port_file(item.get("path", ""))
            and item.get("size", 0) <= max_file_bytes
        ]
        entries.sort(key=lambda item: port_file_priority(item["path"]))
        scan_truncated = bool(tree_payload.get("truncated")) or len(entries) > max_files

        selected_entries = []
        selected_bytes = 0
        for item in entries[:max_files]:
            if selected_bytes + item.get("size", 0) > max_total_bytes:
                scan_truncated = True
                break
            selected_entries.append(item)
            selected_bytes += item.get("size", 0)

        scanned = []
        worker_count = min(PORT_SCAN_MAX_WORKERS, len(selected_entries))
        if worker_count:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                files = executor.map(
                    lambda item: _fetch_port_scan_file(item, headers, max_file_bytes),
                    selected_entries,
                )
                scanned = [file for file in files if file is not None]

        for path, content in scanned:
            scanned_files += 1
            evidence.extend(extract_port_evidence(path, content))
    except (requests.RequestException, KeyError, TypeError, ValueError) as error:
        logging.warning("Unable to collect repository port evidence: %s", error)

    return format_port_evidence(
        evidence,
        scanned_files=scanned_files,
        scan_truncated=scan_truncated,
    )


def fetch_repo_context(repo_url, max_depth=1):
    # First, check if the URL is valid
    if not is_valid_github_url(repo_url):
        logging.error(f"Invalid GitHub repository URL: {repo_url}")
        raise ValueError("Invalid GitHub repository URL")

    logging.info(f"Fetching context from GitHub repository: {repo_url}")
    token = os.getenv("GITHUB_TOKEN")

    parts = repo_url.split("/")
    owner = parts[-2]
    repo = parts[-1]

    contents_api_url = f"https://api.github.com/repos/{owner}/{repo}/contents"
    languages_api_url = f"https://api.github.com/repos/{owner}/{repo}/languages"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}",
    }

    existing_devcontainer = None
    devcontainer_url = None

    root_devcontainer_url = f"{contents_api_url}/.devcontainer.json"
    response = requests.get(root_devcontainer_url, headers=headers)
    if response.status_code == 200:
        existing_devcontainer = requests.get(response.json()["download_url"]).text
        devcontainer_url = response.json()["download_url"]

    if not existing_devcontainer:
        devcontainer_dir_url = f"{contents_api_url}/.devcontainer"
        response = requests.get(devcontainer_dir_url, headers=headers)
        if response.status_code == 200:
            for item in response.json():
                if item["name"] == "devcontainer.json":
                    existing_devcontainer = requests.get(item["download_url"]).text
                    devcontainer_url = item["download_url"]
                    break

    context = []
    total_tokens = 0

    def traverse_dir(api_url, depth=0, prefix=""):
        if depth > max_depth:
            return []

        logging.info(f"Traversing directory: {api_url}")
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()

        structure = []
        important_files = {
            "requirements.txt", "dockerfile", ".gitignore", "package.json",
            "gemfile", "readme.md", "contributing.md", ".env", ".env.example",
            "pipfile", "setup.py", "pipfile.lock", "pyproject.toml",
            "cmakelists.txt", "makefile", "go.mod", "go.sum", "pom.xml",
            "build.gradle", "cargo.toml", "cargo.lock", "composer.json",
            "phpunit.xml", "mix.exs", "pubspec.yaml", "stack.yaml",
            "description", "namespace", "rakefile", "docker-compose.yml",
            "docker-compose.yaml", "compose.yml", "compose.yaml", "procfile",
        }
        large_dirs_to_skip = ["node_modules", "vendor"]

        for item in response.json():
            logging.debug(f"Processing item: {item['name']}")
            if item["type"] == "dir":
                if item["name"] in large_dirs_to_skip:
                    continue
                structure.append(f"{prefix}{item['name']}/")
                structure.extend(
                    traverse_dir(item["url"], depth + 1, prefix=prefix + "    ")
                )
            else:
                structure.append(f"{prefix}{item['name']}")

            if item["type"] == "file" and item["name"].lower() in important_files:
                logging.debug(f"Fetching content of {item['name']}")
                file_content = requests.get(item["download_url"]).text
                content_text = (
                    f"<<SECTION: Content of {item['name']} >>\n{file_content}"
                    + f"\n<<END_SECTION: Content of {item['name']} >>"
                )
                context.append(content_text)

                file_tokens = count_tokens(content_text)
                nonlocal total_tokens
                total_tokens += file_tokens

        return structure

    logging.info("Building repository structure...")
    repo_structure = traverse_dir(contents_api_url)

    logging.info("Adding repository structure to context...")
    repo_structure_text = (
        "<<SECTION: Repository Structure >>\n"
        + "\n".join(repo_structure)
        + "\n<<END_SECTION: Repository Structure >>"
    )
    context.insert(0, repo_structure_text)

    repo_structure_tokens = count_tokens(repo_structure_text)
    total_tokens += repo_structure_tokens

    logging.info("Detecting evidence-backed forwarded ports...")
    port_evidence_context = fetch_port_evidence_context(owner, repo, headers)
    context.append(port_evidence_context)
    total_tokens += count_tokens(port_evidence_context)

    logging.info("Fetching repository languages...")
    languages_response = requests.get(languages_api_url, headers=headers)
    languages_response.raise_for_status()

    logging.info("Adding repository languages to context...")
    languages_data = languages_response.json()
    languages_context = (
        "<<SECTION: Repository Languages >>\n"
        + "\n".join(
            [f"{lang}: {count} lines" for lang, count in languages_data.items()]
        )
        + "\n<<END_SECTION: Repository Languages >>"
    )
    context.append(languages_context)

    languages_tokens = count_tokens(languages_context)
    total_tokens += languages_tokens

    logging.debug(f"Total tokens: {total_tokens}")

    if existing_devcontainer:
        devcontainer_context = (
            "<<SECTION: Existing devcontainer.json >>\n"
            f"{existing_devcontainer}\n"
            "<<END_SECTION: Existing devcontainer.json >>"
        )
        context.append(devcontainer_context)
        total_tokens += count_tokens(devcontainer_context)

    return "\n\n".join(context), existing_devcontainer, devcontainer_url

def check_url_exists(url):
    existing = supabase.table("devcontainers").select("*").eq("url", url).order("created_at", desc=True).limit(1).execute()
    existing_record = existing.data[0] if existing.data else None
    return existing_record is not None, existing_record
