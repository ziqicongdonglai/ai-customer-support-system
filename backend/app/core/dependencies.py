from functools import lru_cache
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

from app.utils.token_counter import TokenCounter

from app.context.recent_strategy import RecentContextStrategy

from app.database.session import get_db

from app.providers.base import BaseLLMProvider
from app.providers.factory import ProviderFactory

from app.repositories.message_repository import MessageRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.business_repository import BusinessRepository
from app.repositories.workflow_repository import WorkflowRepository

from app.services.chat_service import ChatService
from app.services.business_service import BusinessService
from app.services.conversation_service import ConversationService
from app.services.context_builder import ContextBuilder
from app.services.workflow_service import WorkflowService

from app.rag.embeddings import BaseEmbeddingProvider, SentenceTransformerEmbeddingProvider
from app.rag.vector_store import BaseVectorStore, ChromaVectorStore
from app.rag.retriever import BaseRetriever, VectorRetriever


def get_llm_provider() -> BaseLLMProvider:
    return ProviderFactory.create(
        settings.llm_provider
    )

def get_message_repository(
    db: AsyncSession = Depends(get_db),
) -> MessageRepository:
    return MessageRepository(db)

def get_conversation_repository(
    db: AsyncSession = Depends(get_db),
) -> ConversationRepository:

    return ConversationRepository(db)

def get_business_service(
    db: AsyncSession = Depends(get_db),
) -> BusinessService:
    return BusinessService(BusinessRepository(db))

def get_workflow_service(
    db: AsyncSession = Depends(get_db),
    business_service: BusinessService = Depends(get_business_service),
) -> WorkflowService:
    return WorkflowService(WorkflowRepository(db), business_service)

def get_token_counter():
    return TokenCounter()

def get_context_strategy(
    token_counter: TokenCounter = Depends(
        get_token_counter
    ),
):

    return RecentContextStrategy(
        token_counter
    )

def get_context_builder(
    message_repo=Depends(
        get_message_repository
    ),
    strategy=Depends(
        get_context_strategy
    ),
    token_counter=Depends(
        get_token_counter
    ),
):

    return ContextBuilder(
        message_repo,
        strategy,
        token_counter,
    )

@lru_cache(maxsize=1)
def get_retriever() -> BaseRetriever:
    return VectorRetriever(
        embedding_provider=get_embedding_provider(),
        vector_store=get_vector_store(),
        top_k=settings.rag_top_k,
    )

def get_chat_service(
    provider: BaseLLMProvider = Depends(
        get_llm_provider
    ),
    conversation_repo: ConversationRepository = Depends(
        get_conversation_repository
    ),
    message_repo: MessageRepository = Depends(
        get_message_repository
    ),
    context_builder: ContextBuilder = Depends(
        get_context_builder
    ),
    retriever: BaseRetriever = Depends(
        get_retriever
    ),
    business_service: BusinessService = Depends(
        get_business_service
    ),
) -> ChatService:
    return ChatService(
        provider=provider,
        conversation_repo=conversation_repo,
        message_repo=message_repo,
        context_builder=context_builder,
        retriever=retriever,
        business_service=business_service,
    )

def get_conversation_service(
    conversation_repo: ConversationRepository = Depends(
        get_conversation_repository
    ),
    message_repo: MessageRepository = Depends(
        get_message_repository
    )
) -> ConversationService:
    return ConversationService(
        conversation_repo=conversation_repo,
        message_repo=message_repo,
    )

# 缓存 embedding provider
@lru_cache(maxsize=1)
def get_embedding_provider() -> BaseEmbeddingProvider:
    return SentenceTransformerEmbeddingProvider(
        model_name=settings.embedding_model
    )

@lru_cache(maxsize=1)
def get_vector_store() -> BaseVectorStore:
    return ChromaVectorStore(
        persist_path=settings.rag_vector_store_path,
        collection_name=settings.rag_collection_name,
    )
