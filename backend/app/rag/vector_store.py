import chromadb

from abc import ABC, abstractmethod
from app.rag.models import VectorRecord, RetrievedChunk


class BaseVectorStore(ABC):
    @abstractmethod
    def add(
        self,
        records: list[VectorRecord],
    ) -> None:
        pass

    @abstractmethod
    def count(self) -> int:
        pass

    @abstractmethod
    def search(
        self,
        query_embedding: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        pass

class ChromaVectorStore(BaseVectorStore):
    def __init__(
        self,
        persist_path: str,
        collection_name: str,
    ) -> None:
        self.persist_path = persist_path
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=persist_path)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add(
        self, 
        records: list[VectorRecord]
    ) -> None:
        if not records:
            return
        
        embeddings = []
        documents = []
        metadatas = []
        ids = []

        for record in records:
            embeddings.append(record.embedding)
            documents.append(record.content)
            metadatas.append(record.metadata)
            ids.append(record.id)

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

    def count(self) -> int:
        return self.collection.count()

    def search(self, 
        query_embedding: list[float], 
        top_k: int
    ) -> list[RetrievedChunk]:
        if not query_embedding:
            raise ValueError("query_embedding must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be greater than 0")

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=[
                "documents",
                "metadatas",
                "distances"
            ]
        )

        ids = results["ids"][0]
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]
        retrieved_chunks: list[RetrievedChunk] = []

        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            retrieved_chunk = RetrievedChunk(
                chunk_id=chunk_id,
                document_id=metadata["document_id"],
                content=document,
                score=1.0 - distance,
                metadata=metadata
            )

            retrieved_chunks.append(retrieved_chunk)

        return retrieved_chunks