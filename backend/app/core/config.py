import os
from math import isfinite
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.exceptions import ConfigurationException


load_dotenv()


# Settings 只校验配置的存在性、语法、允许值与字段关系；数据库连接、LLM 调用、
# Chroma 初始化和模型加载分别留在 request-time / readiness 边界。
class Settings:
    def __init__(self) -> None:
        self.llm_provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
        if self.llm_provider not in {"mock", "deepseek"}:
            raise ConfigurationException(
                "LLM_PROVIDER must be one of: mock, deepseek"
            )

        self.request_timeout = self._float("REQUEST_TIMEOUT", "60")
        if not isfinite(self.request_timeout) or self.request_timeout <= 0:
            raise ConfigurationException("REQUEST_TIMEOUT must be greater than 0")

        # Retained for compatibility; there is currently no runtime consumer.
        self.context_message_limit = self._int("CONTEXT_MESSAGE_LIMIT", "20")

        self.max_context_tokens = self._int("MAX_CONTEXT_TOKENS", "4000")
        if self.max_context_tokens <= 0:
            raise ConfigurationException("MAX_CONTEXT_TOKENS must be greater than 0")

        self.default_system_prompt = os.getenv(
            "DEFAULT_SYSTEM_PROMPT",
            "You are a helpful AI assistant.",
        )
        self.cors_origins = self._cors_origins()

        # Slice 1 只验证 URL 语法与 driver；数据库连通性和 schema readiness 属于 Slice 2。
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        if not self.database_url:
            raise ConfigurationException("DATABASE_URL is required")
        try:
            database_url = make_url(self.database_url)
        except ArgumentError as exc:
            raise ConfigurationException(
                "DATABASE_URL must be a valid postgresql+asyncpg URL"
            ) from exc
        if database_url.drivername != "postgresql+asyncpg":
            raise ConfigurationException(
                "DATABASE_URL must be a valid postgresql+asyncpg URL"
            )

        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        # Key 是条件配置：Mock 必须能无真实 key 启动，DeepSeek 模式则在启动时要求 key。
        if self.llm_provider == "deepseek" and not self.deepseek_api_key:
            raise ConfigurationException(
                "DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek"
            )
        self.deepseek_base_url = os.getenv(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        )
        self.deepseek_model = os.getenv(
            "DEEPSEEK_MODEL",
            "deepseek-v4-flash",
        )

        self.embedding_model = self._non_empty(
            "EMBEDDING_MODEL",
            "BAAI/bge-small-zh-v1.5",
        )
        self.rag_vector_store_path = self._non_empty(
            "RAG_VECTOR_STORE_PATH",
            "/app/vector_data",
        )
        self.rag_collection_name = self._non_empty(
            "RAG_COLLECTION_NAME",
            # 与业务知识 ingestion 脚本保持一致，避免写入和查询落到不同 collection。
            "business_knowledge",
        )

        self.rag_chunk_size = self._int("RAG_CHUNK_SIZE", "500")
        if self.rag_chunk_size <= 0:
            raise ConfigurationException("RAG_CHUNK_SIZE must be greater than 0")

        self.rag_chunk_overlap = self._int("RAG_CHUNK_OVERLAP", "100")
        if self.rag_chunk_overlap < 0:
            raise ConfigurationException(
                "RAG_CHUNK_OVERLAP must be greater than or equal to 0"
            )
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ConfigurationException(
                "RAG_CHUNK_OVERLAP must be less than RAG_CHUNK_SIZE"
            )

        self.rag_top_k = self._int("RAG_TOP_K", "3")
        if self.rag_top_k <= 0:
            raise ConfigurationException("RAG_TOP_K must be greater than 0")

    @staticmethod
    def _int(name: str, default: str) -> int:
        try:
            return int(os.getenv(name, default))
        except ValueError as exc:
            raise ConfigurationException(f"{name} must be an integer") from exc

    @staticmethod
    def _float(name: str, default: str) -> float:
        try:
            return float(os.getenv(name, default))
        except ValueError as exc:
            raise ConfigurationException(f"{name} must be a number") from exc

    @staticmethod
    def _non_empty(name: str, default: str) -> str:
        value = os.getenv(name, default).strip()
        if not value:
            raise ConfigurationException(f"{name} must not be empty")
        return value

    # 这里只接受浏览器的精确 origin，不接受任意 URL；CORS 也不承担身份认证职责。
    @staticmethod
    def _cors_origins() -> list[str]:
        raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        if not raw_origins.strip():
            raise ConfigurationException("CORS_ORIGINS must not be empty")

        origins = [origin.strip() for origin in raw_origins.split(",")]
        if any(not origin for origin in origins):
            raise ConfigurationException(
                "CORS_ORIGINS must not contain empty origins"
            )

        for origin in origins:
            if origin == "*":
                raise ConfigurationException(
                    "CORS_ORIGINS must not contain wildcard origins"
                )
            try:
                parsed = urlsplit(origin)
                hostname = parsed.hostname
                _ = parsed.port
            except ValueError as exc:
                raise ConfigurationException(
                    "CORS_ORIGINS must contain valid HTTP origins"
                ) from exc
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or not hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ConfigurationException(
                    "CORS_ORIGINS must contain valid HTTP origins"
                )

        return origins


settings = Settings()
