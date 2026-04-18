import logging
from typing import Optional, Literal
from langchain_qdrant import QdrantVectorStore
from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.config.settings import settings

logger = logging.getLogger(__name__)

# --- Defined Literals for Strict LLM Typing ---
DomainType = Literal["docker_stack", "lxc", "physical_network", "proxmox_host", "vm"]
ResourceIdType = Literal["110", "120", "130", "200", "210", "220", "host", "network_infrastructure"]
ContentTypeType = Literal["config_file", "docker_compose", "documentation", "network_topology", "script"]
IpAddressType = Literal["192.168.1.100", "192.168.1.110", "192.168.1.120", "192.168.1.130", "192.168.1.200", "192.168.1.210", "192.168.1.220"]
ServiceNameType = Literal["ai", "bios", "cloudflare-ddns", "cloudflared", "cosmote", "cudy", "dns", "docker", "gaming", "gpu_passthrough", "grafana", "grub", "influxdb", "jellyfin", "langfuse", "linuxdocker", "loki", "media", "navidrome", "nginx", "nginx-proxy-manager", "nvidia", "ollama", "open-webui", "promtail", "proxmox", "qdrant", "technitium", "technitiumdns", "telegraf", "truenas", "ubuntu", "vfio", "whisper", "windows", "wireguard", "zfs", "zte"]
# ----------------------------------------------

def query_knowledge(
    query: str,
    search_size: Literal["normal", "large"] = "normal",
    domain: Optional[DomainType] = None,
    resource_id: Optional[ResourceIdType] = None,
    service_name: Optional[ServiceNameType] = None,
    ip_address: Optional[IpAddressType] = None,
    content_type: Optional[ContentTypeType] = None
) -> str:
    """
    Queries the Home Lab knowledge base for runbooks, Docker Compose files, and network topology.
    Use the optional parameters to strictly filter the results based on known attributes.
    """
    print(f"\n[DEBUG QDRANT] AI requested knowledge base query: '{query}' (Size: {search_size})")
    
    # Explicitly log the filters LLM chose to apply
    print(f"[DEBUG QDRANT] Applied Filters -> domain: {domain} | resource_id: {resource_id} | service_name: {service_name} | ip_address: {ip_address} | content_type: {content_type}")
    
    try:
        # 1. Initialize Embeddings (Must match the ingestion model)
        embeddings = OllamaEmbeddings(
            model=settings.OLLAMA_EMBED_MODEL,
            base_url=settings.OLLAMA_BASE_URL
        )

        # 2. Initialize Qdrant Client
        client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY if settings.QDRANT_API_KEY else None
        )

        vector_store = QdrantVectorStore(
            client=client,
            collection_name="homelab_assistant",
            embedding=embeddings,
        )

        # 3. Build Exact-Match Filters (Hybrid Search)
        must_conditions = []
        if domain:
            must_conditions.append(models.FieldCondition(key="metadata.domain", match=models.MatchValue(value=domain)))
            
        if resource_id:
            # Safely convert numeric strings back to integers for Qdrant
            parsed_id = int(resource_id) if resource_id.isdigit() else resource_id
            must_conditions.append(models.FieldCondition(key="metadata.resource_id", match=models.MatchValue(value=parsed_id)))
            
        if service_name:
            must_conditions.append(models.FieldCondition(key="metadata.service_names", match=models.MatchValue(value=service_name)))
        if ip_address:
            must_conditions.append(models.FieldCondition(key="metadata.ip_address", match=models.MatchValue(value=ip_address)))
        if content_type:
            must_conditions.append(models.FieldCondition(key="metadata.content_type", match=models.MatchValue(value=content_type)))

        qdrant_filter = models.Filter(must=must_conditions) if must_conditions else None

        if must_conditions:
            print(f"[DEBUG QDRANT] Applying {len(must_conditions)} exact-match filters to vector search.")

        # 4. Set Limits based on search_size
        k = 8 if search_size == "large" else 3
        fetch_k = k * 2 

        # 5. Execute MMR Search
        print(f"[DEBUG QDRANT] Executing MMR search for top {k} results...")
        results = vector_store.max_marginal_relevance_search(
            query=query,
            k=k,
            fetch_k=fetch_k,
            filter=qdrant_filter
        )

        if not results and qdrant_filter is not None:
            print(f"[DEBUG QDRANT] 0 results found with strict filters. Automatically retrying semantic search WITHOUT filters...")
            results = vector_store.max_marginal_relevance_search(
                query=query,
                k=k,
                fetch_k=fetch_k,
                filter=None # Drop all filters
            )

        if not results:
            print(f"[DEBUG QDRANT] No results found even after fallback.")
            return f"No documentation found in the knowledge base matching query: '{query}'."

        print(f"[DEBUG QDRANT] Retrieved {len(results)} diverse chunks. Formatting output...")

        # 6. Format the output efficiently for the LLM Context Window
        output = ["--- RETRIEVED KNOWLEDGE BASE CONTEXT ---"]
        for i, doc in enumerate(results):
            point_id = getattr(doc, 'id', None)
            if point_id is None:
                point_id = doc.metadata.get("_id", doc.metadata.get("id", "Unknown ID"))
                
            source = doc.metadata.get("source_file", "Unknown Source")
            section = doc.metadata.get("Section") or doc.metadata.get("Sub-Section") or "General"
            
            # Print to console for debugging
            print(f"[DEBUG QDRANT] Match {i+1} -> ID: {point_id} | Source: {source}")
            
            output.append(f"\n[RESULT {i+1} | ID: {point_id} | Source: {source} | Section: {section}]")
            output.append(doc.page_content)
            output.append("-" * 40)

        return "\n".join(output)

    except Exception as e:
        print(f"[ERROR QDRANT] Vector DB Error: {str(e)}")
        logger.error(f"Vector DB Error: {str(e)}")
        return f"Error querying knowledge base: {str(e)}"