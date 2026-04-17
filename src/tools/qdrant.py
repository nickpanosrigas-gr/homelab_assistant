import logging
from typing import Optional, Literal
from langchain_qdrant import QdrantVectorStore
from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.config.settings import settings

logger = logging.getLogger(__name__)

def query_knowledge(
    query: str,
    search_size: str = "normal",
    domain: Optional[str] = None,
    resource_id: Optional[int] = None,
    service_name: Optional[str] = None,
    ip_address: Optional[str] = None,
    content_type: Optional[str] = None
) -> str:
    """
    Queries the Home Lab knowledge base for runbooks, Docker Compose files, and network topology.
    Use the optional parameters to strictly filter the results based on known attributes.
    """
    print(f"\n[DEBUG QDRANT] AI requested knowledge base query: '{query}' (Size: {search_size})")
    
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
            must_conditions.append(models.FieldCondition(key="metadata.service_names", match=models.MatchValue(value=service_name)))
        if ip_address:
            must_conditions.append(models.FieldCondition(key="metadata.ip_address", match=models.MatchValue(value=ip_address)))
        if content_type:
            must_conditions.append(models.FieldCondition(key="metadata.content_type", match=models.MatchValue(value=content_type)))

        qdrant_filter = models.Filter(must=must_conditions) if must_conditions else None

        if must_conditions:
            print(f"[DEBUG QDRANT] Applying {len(must_conditions)} exact-match filters.")

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

        if not results:
            print(f"[DEBUG QDRANT] No results found.")
            return f"No documentation found in the knowledge base matching query: '{query}' and provided filters."

        print(f"[DEBUG QDRANT] Retrieved {len(results)} diverse chunks. Formatting output...")

        # 6. Format the output efficiently for the LLM Context Window
        output = ["--- RETRIEVED KNOWLEDGE BASE CONTEXT ---"]
        for i, doc in enumerate(results):
            point_id = getattr(doc, 'id', None)
            if point_id is None:
                point_id = doc.metadata.get("_id", doc.metadata.get("id", "Unknown ID"))
                
            source = doc.metadata.get("source_file", "Unknown Source")
            section = doc.metadata.get("Section") or doc.metadata.get("Sub-Section") or "General"
            
            # --- ADDED DEBUG CONSOLE PRINT HERE ---
            print(f"[DEBUG QDRANT] Match {i+1} -> ID: {point_id} | Source: {source}")
            
            output.append(f"\n[RESULT {i+1} | ID: {point_id} | Source: {source} | Section: {section}]")
            output.append(doc.page_content)
            output.append("-" * 40)

        return "\n".join(output)

    except Exception as e:
        print(f"[ERROR QDRANT] Vector DB Error: {str(e)}")
        logger.error(f"Vector DB Error: {str(e)}")
        return f"Error querying knowledge base: {str(e)}"