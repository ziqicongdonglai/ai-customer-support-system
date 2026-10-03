from dataclasses import dataclass
from app.rag.models import RetrievedChunk

@dataclass
class ContextBuildResult:
    messages: list[dict]
    used_chunks: list[RetrievedChunk]