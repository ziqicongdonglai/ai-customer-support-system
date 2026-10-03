import logging

from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.stream import router as stream_router
from app.api.routes.memory import router as memory_router
from app.api.routes.conversations import router as conversation_router
from app.api.routes.workflows import router as workflow_router
from app.core.handlers import add_exception_handlers
from app.core.logging import setup_logging
from app.middleware.request_id import RequestIDMiddleware

setup_logging()

app = FastAPI(
    title="AI Chat Backend",
    version="0.1.0",
    description="AI Chat Backend for AI Customer Support System",
)

app.add_middleware(RequestIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(stream_router)
app.include_router(memory_router)
app.include_router(conversation_router)
app.include_router(workflow_router)

add_exception_handlers(app)

logger = logging.getLogger(__name__)

logger.info("AI Chat Backend started")

@app.get("/")
async def root():
    return {"message": "AI Chat Backend is running"}
