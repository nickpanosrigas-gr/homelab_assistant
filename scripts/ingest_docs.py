import os
import glob
import frontmatter
import logging
import hashlib
from typing import List

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from src.config.settings import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

def process_markdown_files() -> List[Document]:
    """Reads .md files and extracts YAML frontmatter. Treats each file as a single coherent document."""
    documents = []
    
    # Find all markdown files in the data directory
    md_files = glob.glob(os.path.join(DATA_DIR, "*.md"))
    
    if not md_files:
        logger.warning(f"No Markdown files found in {DATA_DIR}")
        return documents

    for file_path in md_files:
        logger.info(f"Processing: {os.path.basename(file_path)}")
        
        try:
            # 1. Parse YAML Frontmatter & Markdown Content
            with open(file_path, "r", encoding="utf-8") as f:
                post = frontmatter.load(f)
                
            metadata = post.metadata
            content = post.content
            
            filename = os.path.basename(file_path)
            
            # OPTIMIZATION: Generate a deterministic ID based on the filename.
            # This ensures that updating a file overwrites its old chunk in Qdrant 
            # instead of creating a duplicate.
            doc_id = hashlib.md5(filename.encode()).hexdigest()
            
            # Append reference metadata
            metadata["source_file"] = filename
            metadata["_id"] = doc_id 
            
            # 2. Create the final Langchain Document (No splitting)
            doc = Document(
                page_content=content, 
                metadata=metadata,
                id=doc_id # Explicitly pass the ID to LangChain
            )
            documents.append(doc)
                
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {str(e)}")

    return documents

def main():
    logger.info("Starting Home Lab Document Ingestion...")
    
    # 1. Process files into LangChain Documents
    docs = process_markdown_files()
    if not docs:
        logger.error("Exiting: No documents to ingest.")
        return
        
    logger.info(f"Generated {len(docs)} documents for ingestion.")

    # 2. Initialize Ollama Embeddings
    logger.info(f"Initializing Embeddings via Ollama ({settings.OLLAMA_EMBED_MODEL})...")
    embeddings = OllamaEmbeddings(
        model=settings.OLLAMA_EMBED_MODEL,
        base_url=settings.OLLAMA_BASE_URL
    )
    
    # 3. Initialize Qdrant Client
    logger.info(f"Connecting to Qdrant at {settings.QDRANT_URL}...")
    client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY if settings.QDRANT_API_KEY else None
    )
    
    # Ensure collection exists; Nomic embed text uses 768 dimensions
    if not client.collection_exists(settings.QDRANT_COLLECTION_NAME):
        logger.info(f"Creating new Qdrant collection: {settings.QDRANT_COLLECTION_NAME}")
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )

    # 4. Ingest into Vector Store
    logger.info(f"Pushing {len(docs)} documents to Qdrant...")
    
    # OPTIMIZATION: Extract the deterministic IDs to pass to from_documents
    doc_ids = [doc.id for doc in docs]
    
    QdrantVectorStore.from_documents(
        docs,
        embeddings,
        ids=doc_ids, # Pass the IDs to Qdrant
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY if settings.QDRANT_API_KEY else None,
        collection_name=settings.QDRANT_COLLECTION_NAME,
        force_recreate=False # Set to False so we update (upsert) instead of wipe
    )
    
    logger.info("✅ Ingestion complete! Knowledge base is updated and ready for retrieval.")

if __name__ == "__main__":
    main()