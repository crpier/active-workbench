"""Models for K3s operations."""

from typing import Optional

from pydantic import BaseModel


class K3sApplyRequest(BaseModel):
    """Request payload for applying a manifest to the cluster."""

    manifest: str
    namespace: Optional[str] = None


class K3sDeleteRequest(BaseModel):
    """Request payload for deleting a resource from the cluster."""

    kind: str
    name: str
    namespace: Optional[str] = None


class K3sCommandResponse(BaseModel):
    """Response for kubectl command execution."""

    status: str
    output: str

