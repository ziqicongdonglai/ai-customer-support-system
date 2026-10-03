from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.rag.models import RetrievedChunk

if TYPE_CHECKING:
    from app.rag.embeddings import BaseEmbeddingProvider
    from app.rag.vector_store import BaseVectorStore


class BaseRetriever(ABC):
    @abstractmethod
    def retrieve(
        self,
        query:str,
    ) -> list[RetrievedChunk]:
        pass

class VectorRetriever(BaseRetriever):
    def __init__(
        self,
        embedding_provider: BaseEmbeddingProvider,
        vector_store: BaseVectorStore,
        top_k: int,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.top_k = top_k

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        query_embedding = self.embedding_provider.embed_query(query)
        results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=self.top_k,
        )
        return results
