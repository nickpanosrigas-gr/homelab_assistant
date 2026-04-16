import requests
from typing import Literal

# Define the exact allowed values to help the LLM strictly format its requests
ServiceName = Literal["ollama", "technitium", "jellyfin", "navidrome", "vaultwarden", "nginx"]

# Centralized URL configuration
SERVICE_ENDPOINTS = {
    "ollama": {"local": "http://192.168.1.220:11434"},
    "technitium": {"local": "http://192.168.1.200:5380"},
    "jellyfin": {
        "local": "http://192.168.1.210:8096",
        "domain": "https://jellyfin.pali.autos"
    },
    "navidrome": {
        "local": "http://192.168.1.120:4533",
        "domain": "https://navidrome.pali.autos"
    },
    "vaultwarden": {
        "local": "http://192.168.1.120:11001",
        "domain": "https://vw.pali.autos"
    },
    "nginx": {"local": "http://192.168.1.120:80"}
}

class PingClient:
    def _execute_ping(self, url: str) -> dict:
        """Helper method to handle the actual HTTP request and error catching."""
        try:
            response = requests.get(url, timeout=5)
            latency_ms = int(response.elapsed.total_seconds() * 1000)
            
            if response.status_code < 400:
                return {"status": "UP", "code": response.status_code, "latency": f"{latency_ms}ms"}
            else:
                return {"status": "DEGRADED", "code": response.status_code, "latency": f"{latency_ms}ms"}
                
        except requests.exceptions.Timeout:
            return {"status": "DOWN", "error": "Timeout (Exceeded 5s)"}
        except requests.exceptions.ConnectionError:
            return {"status": "DOWN", "error": "Connection Refused or DNS Failure"}
        except requests.exceptions.RequestException as e:
            return {"status": "DOWN", "error": type(e).__name__}

    def ping_service(self, service_name: ServiceName) -> str:
        """
        Use to ping a service to check if it is online. 
        You must provide the service name (e.g., 'jellyfin').
        """
        service_name = service_name.lower()
        print(f"\n[DEBUG PING] AI requested ping for service: {service_name}")
        
        if service_name not in SERVICE_ENDPOINTS:
            return f"ERROR: Invalid service name. Allowed values: {', '.join(SERVICE_ENDPOINTS.keys())}"
            
        endpoints = SERVICE_ENDPOINTS[service_name]
        results = {}
        
        # Ping all endpoints associated with the service (local and domain if applicable)
        for endpoint_type, url in endpoints.items():
            print(f"[DEBUG PING] Executing GET request for {endpoint_type} URL: {url}")
            results[endpoint_type] = self._execute_ping(url)
            
        # Logic for Dual-Endpoint Services (Local + Domain)
        if "domain" in endpoints:
            loc = results["local"]
            dom = results["domain"]
            
            if loc["status"] == "UP" and dom["status"] == "UP":
                result_str = f"STATUS: ONLINE | Both Local ({loc['latency']}) and Domain ({dom['latency']}) are UP."
            elif loc["status"] == "UP" and dom["status"] != "UP":
                err = dom.get("error", f"HTTP {dom.get('code')}")
                result_str = f"STATUS: PARTIAL OUTAGE | Local is UP ({loc['latency']}), but Domain is DOWN/DEGRADED ({err})."
            elif loc["status"] != "UP" and dom["status"] == "UP":
                err = loc.get("error", f"HTTP {loc.get('code')}")
                result_str = f"STATUS: ROUTING ISSUE | Domain is UP ({dom['latency']}), but Local is DOWN/DEGRADED ({err})."
            else:
                loc_err = loc.get("error", f"HTTP {loc.get('code')}")
                dom_err = dom.get("error", f"HTTP {dom.get('code')}")
                result_str = f"STATUS: OFFLINE | Both endpoints are DOWN. Local: {loc_err} | Domain: {dom_err}"
                
            print(f"[DEBUG PING] Result: {result_str}")
            return result_str
            
        # Logic for Single-Endpoint Services (Local only)
        else:
            loc = results["local"]
            if loc["status"] == "UP":
                result_str = f"STATUS: ONLINE | CODE: {loc['code']} | LATENCY: {loc['latency']}"
            elif loc["status"] == "DEGRADED":
                result_str = f"STATUS: DEGRADED | CODE: {loc['code']} | LATENCY: {loc['latency']}"
            else:
                result_str = f"STATUS: OFFLINE | ERROR: {loc['error']}"
                
            print(f"[DEBUG PING] Result: {result_str}")
            return result_str