from abc import ABC, abstractmethod
from pathlib import Path
from app.rag.models import Document

class BaseDocumentLoader(ABC):

    @abstractmethod
    def load(self) -> Document:
        pass

class LocalTextLoader(BaseDocumentLoader):
    SUPPORTED_EXTENSIONS = {".txt", ".md"}

    def __init__(
        self,
        path: str | Path,
    ) -> None:
        
        self.path = Path(path)

    def load(self) -> Document:
        if not self.path.exists() or not self.path.is_file():
            raise FileNotFoundError(f"File not found: {self.path}")
        
        file_suffix = self.path.suffix.lower()
        if file_suffix not in self.SUPPORTED_EXTENSIONS:
            raise ValueError("Unsupported file type")
        
        content = self.path.read_text("utf-8")

        return Document(
            content= content, 
            metadata = {
                "source": str(self.path),
                "filename": self.path.name,
                "file_type": file_suffix,
        })