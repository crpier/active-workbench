"""Service helpers for interacting with a K3s cluster."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Optional

from ..config import get_config


class K3sClient:
    """Thin wrapper around kubectl for K3s operations."""

    def __init__(self) -> None:
        config = get_config()
        self.kubeconfig_path = config.k3s_kubeconfig

    def list_nodes(self) -> list[dict[str, Any]]:
        """Return a simplified view of cluster nodes."""
        payload = self._run_json(["get", "nodes", "-o", "json"])
        return [self._summarize_node(item) for item in payload.get("items", [])]

    def list_namespaces(self) -> list[str]:
        """Return all namespaces in the cluster."""
        payload = self._run_json(["get", "namespaces", "-o", "json"])
        return [item["metadata"]["name"] for item in payload.get("items", [])]

    def list_pods(self, namespace: str) -> list[dict[str, Any]]:
        """Return a simplified view of pods in a namespace."""
        payload = self._run_json(["get", "pods", "-n", namespace, "-o", "json"])
        return [self._summarize_pod(item) for item in payload.get("items", [])]

    def apply_manifest(self, manifest: str, namespace: Optional[str]) -> str:
        """Apply a manifest to the cluster."""
        args = ["apply", "-f", "-"]
        if namespace:
            args.extend(["-n", namespace])
        return self._run_kubectl(args, input_data=manifest)

    def delete_resource(self, kind: str, name: str, namespace: Optional[str]) -> str:
        """Delete a resource from the cluster."""
        args = ["delete", kind, name]
        if namespace:
            args.extend(["-n", namespace])
        return self._run_kubectl(args)

    def _run_json(self, args: list[str]) -> dict[str, Any]:
        output = self._run_kubectl(args)
        return json.loads(output) if output else {}

    def _run_kubectl(self, args: list[str], input_data: Optional[str] = None) -> str:
        command = ["kubectl", f"--kubeconfig={self.kubeconfig_path}", *args]
        result = subprocess.run(
            command,
            input=input_data,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "kubectl command failed")
        return result.stdout.strip()

    @staticmethod
    def _summarize_node(item: dict[str, Any]) -> dict[str, Any]:
        status = "unknown"
        for condition in item.get("status", {}).get("conditions", []):
            if condition.get("type") == "Ready":
                status = "ready" if condition.get("status") == "True" else "not-ready"
                break
        return {
            "name": item.get("metadata", {}).get("name"),
            "status": status,
            "roles": item.get("metadata", {}).get("labels", {}).get(
                "kubernetes.io/role"
            ),
            "version": item.get("status", {}).get("nodeInfo", {}).get("kubeletVersion"),
        }

    @staticmethod
    def _summarize_pod(item: dict[str, Any]) -> dict[str, Any]:
        metadata = item.get("metadata", {})
        status = item.get("status", {})
        return {
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "phase": status.get("phase"),
            "node": status.get("nodeName"),
            "start_time": status.get("startTime"),
        }

