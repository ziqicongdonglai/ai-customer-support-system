from abc import ABC, abstractmethod
from app.rag.models import Document, Chunk


class BaseChunkingStrategy(ABC):

    @abstractmethod
    def split(self, document: Document) -> list[Chunk]:
        pass

class FixedSizeChunkingStrategy(BaseChunkingStrategy):

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")

        if chunk_overlap < 0:
            raise ValueError("chunk_overlap cannot be negative")
        
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, document: Document) -> list[Chunk]:
        content = document.content
        start = 0
        chunk_index = 0
        chunks = []

        if not content.strip():
            return []

        while start < len(content):

            end = start + self.chunk_size
            chunk_content = content[start:end].strip()

            if chunk_content:

                chunk = Chunk(
                    document_id=document.id,
                    content=chunk_content.strip(),
                    chunk_index=chunk_index,
                    metadata=document.metadata.copy()
                )

                chunks.append(chunk)
                chunk_index += 1

            start += self.chunk_size - self.chunk_overlap

        return chunks