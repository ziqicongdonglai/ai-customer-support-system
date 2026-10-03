from app.rag.loaders import LocalTextLoader
from app.rag.chunking import BaseChunkingStrategy
from app.rag.embeddings import BaseEmbeddingProvider
from app.rag.vector_store import BaseVectorStore
from app.rag.models import VectorRecord


class KnowledgeIngestor:
    def __init__(
        self,
        chunking_strategy: BaseChunkingStrategy,
        embedding_provider: BaseEmbeddingProvider,
        vector_store: BaseVectorStore,
    ) -> None:
        self.chunking_strategy = chunking_strategy
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    def ingest(self, path: str) -> int:
        loader = LocalTextLoader(path=path)
        document = loader.load()
        chunks = self.chunking_strategy.split(document)
        if not chunks:
            return 0
        texts = [
            chunk.content
            for chunk in chunks
        ]
        embeddings = self.embedding_provider.embed_documents(texts)
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        records: list[VectorRecord] = []
        for chunk, embedding in zip(chunks, embeddings):
            record = VectorRecord(
                id=chunk.id,
                content=chunk.content,
                embedding=embedding,
                metadata={
                    **chunk.metadata,
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.chunk_index,
                }
            )
            records.append(record)
        self.vector_store.add(records)
        return len(records)