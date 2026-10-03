"""Ingest the business corpus once into its isolated runtime collection.

Run from the backend directory: python -m app.scripts.ingest_business_knowledge
Select it for chat at process startup with RAG_COLLECTION_NAME=business_knowledge.
"""
import os
from pathlib import Path

from app.core.config import settings
from app.core.dependencies import get_embedding_provider
from app.rag.chunking import FixedSizeChunkingStrategy
from app.rag.ingestion import KnowledgeIngestor
from app.rag.vector_store import ChromaVectorStore


COLLECTION_NAME = "business_knowledge"
KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "data" / "business_knowledge"


def main():
    store = ChromaVectorStore(settings.rag_vector_store_path, COLLECTION_NAME)
    if store.count():
        raise SystemExit("Business collection is not empty; refusing duplicate ingestion. No records changed.")

    # Phase 2 evidence applies to this corpus only, not Mission 3 global settings.
    ingestor = KnowledgeIngestor(
        FixedSizeChunkingStrategy(100, 20),
        get_embedding_provider(),
        store,
    )
    # This standalone process loads basenames so source metadata contains no path.
    os.chdir(KNOWLEDGE_DIR)
    inserted = sum(ingestor.ingest(path.name) for path in sorted(Path('.').glob('*.md')))
    print(f"Collection: {COLLECTION_NAME}; inserted: {inserted}; count: {store.count()}")


if __name__ == "__main__":
    main()
