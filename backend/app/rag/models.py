from dataclasses import dataclass, field
from typing import Any
import uuid


@dataclass
class Document:
    content: str
    # source、filename、file_type
    metadata: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass
class Chunk:
    document_id: str
    content: str
    chunk_index: int
    metadata: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass
class VectorRecord:
    # chunk id
    id: str
    content: str
    embedding: list[float]
    metadata: dict[str, Any]

@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    content: str
    score: float
    metadata: dict[str, Any]