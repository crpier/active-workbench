"""API routes for K3s operations."""

from fastapi import APIRouter, HTTPException

from ..models.k3s import K3sApplyRequest, K3sCommandResponse, K3sDeleteRequest
from ..services.k3s import K3sClient

router = APIRouter(prefix="/api/k3s", tags=["k3s"])
client = K3sClient()


@router.get("/nodes")
async def list_nodes():
    """List cluster nodes."""
    try:
        return {"status": "ok", "nodes": client.list_nodes()}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/namespaces")
async def list_namespaces():
    """List cluster namespaces."""
    try:
        return {"status": "ok", "namespaces": client.list_namespaces()}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/pods/{namespace}")
async def list_pods(namespace: str):
    """List pods in a namespace."""
    try:
        return {"status": "ok", "pods": client.list_pods(namespace)}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/apply", response_model=K3sCommandResponse)
async def apply_manifest(payload: K3sApplyRequest):
    """Apply a manifest to the cluster."""
    try:
        output = client.apply_manifest(payload.manifest, payload.namespace)
        return K3sCommandResponse(status="ok", output=output)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/resource", response_model=K3sCommandResponse)
async def delete_resource(payload: K3sDeleteRequest):
    """Delete a resource from the cluster."""
    try:
        output = client.delete_resource(payload.kind, payload.name, payload.namespace)
        return K3sCommandResponse(status="ok", output=output)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

