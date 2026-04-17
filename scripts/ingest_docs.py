import os
import glob
import frontmatter
import logging
from typing import List

from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

# Import your settings configuration
from src.config.settings import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Collection name as specified in your architecture docs
COLLECTION_NAME = "homelab_assistant"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

def process_markdown_files() -> List[Document]:
    """Reads .md files, extracts YAML frontmatter, and chunks by Markdown headers."""
    documents = []
    
    # Target headers for cohesive chunking
    headers_to_split_on = [
        ("##", "Section"),
        ("###", "Sub-Section")
    ]
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    
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
                
            base_metadata = post.metadata
            content = post.content
            
            # Add the source filename for reference
            base_metadata["source_file"] = os.path.basename(file_path)
            
            # 2. Split the markdown content by headers
            splits = markdown_splitter.split_text(content)
            
            # 3. Merge Frontmatter Metadata with Header Metadata
            for split in splits:
                # Merge the dictionaries. Header metadata (like "Section") joins the base frontmatter.
                merged_metadata = {**base_metadata, **split.metadata}
                
                # Create the final Langchain Document
                doc = Document(page_content=split.page_content, metadata=merged_metadata)
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
        
    logger.info(f"Generated {len(docs)} chunks from Markdown files.")

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
    if not client.collection_exists(COLLECTION_NAME):
        logger.info(f"Creating new Qdrant collection: {COLLECTION_NAME}")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )

    # 4. Ingest into Vector Store
    logger.info(f"Pushing {len(docs)} document chunks to Qdrant...")
    
    # QdrantVectorStore.from_documents handles the batch uploading seamlessly
    QdrantVectorStore.from_documents(
        docs,
        embeddings,
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY if settings.QDRANT_API_KEY else None,
        collection_name=COLLECTION_NAME,
        force_recreate=True # Set to False in production if you only want to append
    )
    
    logger.info("✅ Ingestion complete! Knowledge base is updated and ready for retrieval.")

if __name__ == "__main__":
    main()