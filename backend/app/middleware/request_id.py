from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import Response

from app.core.context import request_id_context


class RequestIDMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = str(uuid4())

        request.state.request_id = request_id

        token = request_id_context.set(request_id)

        try:
            response = await call_next(request)

            response.headers["X-Request-ID"] = request_id

            return response
        finally:
            request_id_context.reset(token)