import logging
from typing import Optional
from langchain_qdrant import QdrantVectorStore
from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.config.settings import settings

logger = logging.getLogger(__name__)

def query_knowledge(
    query: str,
    domain: Optional[str] = None,
    resource_id: Optional[int] = None,
    service_name: Optional[str] = None,
    ip_address: Optional[str] = None,
    content_type: Optional[str] = None
) -> str:
    """
    Queries the Home Lab knowledge base for runbooks, Docker Compose files, and network topology.
    Use the optional parameters to strictly filter the results based on known attributes.
    
    Args:
        query: The semantic search string (e.g., "How does the GPU passthrough work?").
        domain: Filter by layer (e.g., "proxmox_host", "vm", "lxc", "docker_stack").
        resource_id: Filter by the Proxmox ID (e.g., 130, 220, 110).
        service_name: Filter by application (e.g., "truenas", "ollama", "windows").
        ip_address: Filter by specific IP (e.g., "192.168.1.120").
        content_type: Filter by format (e.g., "config_file", "docker_compose").
    """
    logger.info(f"AI requested knowledge base query: '{query}'")
    
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
            must_conditions.append(models.FieldCondition(key="metadata.resource_id", match=models.MatchValue(value=resource_id)))
        if service_name:
            # Qdrant automatically checks inside lists, so if service_names is ["grafana", "loki"], searching "loki" matches!
            must_conditions.append(models.FieldCondition(key="metadata.service_names", match=models.MatchValue(value=service_name)))
        if ip_address:
            must_conditions.append(models.FieldCondition(key="metadata.ip_address", match=models.MatchValue(value=ip_address)))
        if content_type:
            must_conditions.append(models.FieldCondition(key="metadata.content_type", match=models.MatchValue(value=content_type)))

        # Compile the Qdrant filter object (if any filters were provided)
        qdrant_filter = models.Filter(must=must_conditions) if must_conditions else None

        # 4. Execute the Search (Fetch top 3 most relevant chunks)
        results = vector_store.similarity_search(
            query=query,
            k=3,
            filter=qdrant_filter
        )

        if not results:
            return f"No documentation found in the knowledge base matching query: '{query}' and provided filters."

        # 5. Format the output efficiently for the LLM Context Window
        output = ["--- RETRIEVED KNOWLEDGE BASE CONTEXT ---"]
        for i, doc in enumerate(results):
            source = doc.metadata.get("source_file", "Unknown Source")
            section = doc.metadata.get("Section") or doc.metadata.get("Sub-Section") or "General"
            
            output.append(f"\n[RESULT {i+1} | Source: {source} | Section: {section}]")
            output.append(doc.page_content)
            output.append("-" * 40)

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Vector DB Error: {str(e)}")
        return f"Error querying knowledge base: {str(e)}"