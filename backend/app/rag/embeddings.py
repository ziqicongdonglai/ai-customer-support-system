from abc import ABC, abstractmethod
from sentence_transformers import SentenceTransformer

class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def embed_documents(
        self, 
        texts: list[str],
    ) -> list[list[float]]:
        pass

    @abstractmethod
    def embed_query(
        self, 
        text: str,
    ) -> list[float]:
        pass

class SentenceTransformerEmbeddingProvider(BaseEmbeddingProvider):

    def __init__(
        self,
        model_name: str
    ) -> None:
        self.model_name = model_name
        self.model = None

    def _get_model(self) -> SentenceTransformer:
        if self.model is None:
            self.model = SentenceTransformer(
                self.model_name
            )

        return self.model
    
    def embed_documents(
        self, 
        texts: list[str]
    ) -> list[list[float]]:
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("texts must not contain blank values")

        model = self._get_model()
        embeddings = model.encode(texts).tolist()
        return embeddings
    
    def embed_query(
        self, 
        text: str
    ) -> list[float]:
        if not text.strip():
            raise ValueError("text must not be blank")
        model = self._get_model()
        embedding = model.encode(text).tolist()
        return embedding