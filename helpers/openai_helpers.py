import os
import logging
from openai import AzureOpenAI
import instructor


DEVCONTAINER_SYSTEM_PROMPT = """You generate secure, evidence-based devcontainer.json files.
Base forwarded ports on explicit repository code, configuration, commands, or documentation.
Never default to port 8000, copy a port only from an example, or invent a port when the
repository provides no supporting evidence."""


def setup_azure_openai():
    logging.info("Setting up Azure OpenAI client...")
    return AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    )

def setup_instructor(openai_client):
    logging.info("Setting up Instructor client...")
    return instructor.patch(openai_client)


def build_devcontainer_messages(prompt):
    """Build consistent generation messages with evidence-based port guidance."""

    return [
        {"role": "system", "content": DEVCONTAINER_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


def check_env_vars():
    required_vars = [
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "MODEL",
        "GITHUB_TOKEN",
    ]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        print(
            f"Missing environment variables: {', '.join(missing_vars)}. "
            "Please configure the env vars file properly."
        )
        return False
    return True
