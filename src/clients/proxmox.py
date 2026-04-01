import requests
import urllib3
from typing import Dict, Any, Optional
from src.config.settings import settings

# Disable warnings for self-signed certificates in the homelab
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class ProxmoxClient:
    """API wrapper for Proxmox VE."""

    def __init__(self):
        self.base_url = f"https://{settings.PROXMOX_IP}:8006/api2/json"
        self.node = settings.PROXMOX_NODE
        self.headers = {
            "Authorization": f"PVEAPIToken={settings.PROXMOX_TOKEN_ID}={settings.PROXMOX_TOKEN_SECRET}"
        }

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Internal helper for making API requests."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = requests.request(
            method=method,
            url=url,
            headers=self.headers,
            verify=False,
            **kwargs
        )
        response.raise_for_status()
        return response.json().get("data", {})

    def get_vm_status(self, vmid: int) -> Dict[str, Any]:
        """Fetch the current status of a specific VM or LXC."""
        # Note: Proxmox differentiates between qemu (VMs) and lxc. 
        # We try qemu first, if it fails, we try lxc.
        try:
            return self._request("GET", f"nodes/{self.node}/qemu/{vmid}/status/current")
        except requests.exceptions.HTTPError:
            return self._request("GET", f"nodes/{self.node}/lxc/{vmid}/status/current")

    def get_node_status(self) -> Dict[str, Any]:
        """Fetch the current health and utilization of the Proxmox node."""
        return self._request("GET", f"nodes/{self.node}/status")
        
    def is_gaming_vm_running(self) -> bool:
        """Specific fast-fail check for the Gaming VM (ID: 130)."""
        try:
            status = self.get_vm_status(130)
            return status.get("status") == "running"
        except Exception:
            return False