import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    ActiveWorkflowConflictException,
    ConfigurationException,
    ProviderException,
    ConversationNotFoundException,
    WorkflowUnavailableException,
)
from app.schemas.common import CommonResponse

logger = logging.getLogger(__name__)

def create_error_response(
    status_code: int,
    code: int,
    message: str,
) -> JSONResponse:
    response = CommonResponse[None](
        code=code,
        message=message,
        data=None,
        success=False,
    )

    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(),
    )


def add_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProviderException)
    async def provider_exception_handler(
        request: Request,
        exc: ProviderException,
    ) -> JSONResponse:

        logger.warning(
            "Provider exception: %s", 
            str(exc),
        )

        return create_error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code=1001,
            message=str(exc),
        )

    @app.exception_handler(ConfigurationException)
    async def configuration_exception_handler(
        request: Request,
        exc: ConfigurationException,
    ) -> JSONResponse:

        logger.error(
            "Configuration exception: %s", 
            str(exc),
        )

        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code=1002,
            message=str(exc),
        )

    @app.exception_handler(
        ConversationNotFoundException
    )
    async def conversation_not_found_handler(
        request: Request,
        exc: ConversationNotFoundException,
    ):

        logger.warning(
            "Conversation not found: %s",
            str(exc),
        )

        return create_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code=1003,
            message=str(exc),
        )

    @app.exception_handler(ActiveWorkflowConflictException)
    async def active_workflow_conflict_handler(
        request: Request,
        exc: ActiveWorkflowConflictException,
    ) -> JSONResponse:
        return create_error_response(
            status_code=status.HTTP_409_CONFLICT,
            code=1004,
            message=str(exc),
        )

    @app.exception_handler(WorkflowUnavailableException)
    async def workflow_unavailable_handler(
        request: Request,
        exc: WorkflowUnavailableException,
    ) -> JSONResponse:
        return create_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code=1005,
            message=str(exc),
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:

        logger.exception(
            "Unexpected server error"
        )

        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code=9999,
            message="Internal server error",
        )
