# schemas.py
from pydantic import BaseModel, Field
from typing import Optional


class DevContainerModel(BaseModel):
    name: str = Field(description="Name of the dev container")
    image: str = Field(description="Docker image to use")
    features: dict[str, dict] = Field(
        default_factory=dict,
        description=(
            "Versioned Dev Container Feature IDs mapped to their option objects; "
            "empty when no catalog feature is supported by repository evidence"
        ),
    )
    forwardPorts: Optional[list[int]] = Field(
        description="Ports to forward from the container to the local machine"
    )
    customizations: Optional[dict] = Field(
        None, description="Tool-specific configuration"
    )
    settings: Optional[dict] = Field(
        None, description="VS Code settings to configure the development environment"
    )
    postCreateCommand: Optional[str] = Field(
        description="Command to run after creating the container"
    )
