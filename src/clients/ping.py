import requests

class PingClient:
    def ping_service(self, url: str) -> str:
        """
        Use to ping a service to check if it is online. You must provide the full HTTP/HTTPS URL.
        
        ALLOWED URLS:
        - TrueNAS VM: http://192.168.1.110
        - Docker Host: http://192.168.1.120
        - Technitium DNS Local: http://192.168.1.200:5380
        - Jellyfin Domain: https://jellyfin.pali.autos
        - Navidrome Domain: https://navidrome.pali.autos
        - Vaultwarden Domain: https://vw.pali.autos
        - Wireguard Domain: https://wireguard.pali.autos
        - n8n Local: http://192.168.1.120:5678
        - Open WebUI: https://owu.pali.autos
        - Grafana Local: http://192.168.1.120:3001
        - Radarr Local: http://192.168.1.120:7878
        - Sonarr Local: http://192.168.1.120:8989
        - qBittorrent Local: http://192.168.1.120:8080
        """
        try:
            # Short timeout so the agent doesn't hang forever on offline services
            response = requests.get(url, timeout=5)
            if response.status_code < 400:
                return f"SUCCESS: {url} is ONLINE (Status {response.status_code})."
            else:
                return f"WARNING: {url} returned status code {response.status_code}."
        except requests.exceptions.RequestException as e:
            return f"ERROR: {url} is UNREACHABLE. Exception: {str(e)}"