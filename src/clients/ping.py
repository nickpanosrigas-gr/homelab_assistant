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
        print(f"\n[DEBUG PING] AI requested ping for URL: {url}")
        
        try:
            print("[DEBUG PING] Executing GET request with 5s timeout...")
            response = requests.get(url, timeout=5)
            
            # Calculate latency in milliseconds - Highly valuable for LLM context!
            latency_ms = int(response.elapsed.total_seconds() * 1000)
            
            if response.status_code < 400:
                llm_payload = f"STATUS: UP | CODE: {response.status_code} | LATENCY: {latency_ms}ms"
                print(f"[DEBUG PING] Result: {llm_payload}")
                return llm_payload
            else:
                llm_payload = f"STATUS: DEGRADED | CODE: {response.status_code} | LATENCY: {latency_ms}ms"
                print(f"[DEBUG PING] Result: {llm_payload}")
                return llm_payload
                
        # Catching specific exceptions gives the LLM precise reasons for failures
        except requests.exceptions.Timeout:
            error_msg = "STATUS: DOWN | ERROR: Timeout (Exceeded 5s)"
            print(f"[DEBUG PING] Result: {error_msg}")
            return error_msg
        except requests.exceptions.ConnectionError:
            error_msg = "STATUS: DOWN | ERROR: Connection Refused or DNS Failure"
            print(f"[DEBUG PING] Result: {error_msg}")
            return error_msg
        except requests.exceptions.RequestException as e:
            error_msg = f"STATUS: DOWN | ERROR: {type(e).__name__}"
            print(f"[DEBUG PING] EXCEPTION CAUGHT: {str(e)}")
            return error_msg