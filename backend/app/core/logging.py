import logging

from app.core.context import request_id_context


class RequestIDFilter(logging.Filter):

    def filter(
        self,
        record: logging.LogRecord,
    ) -> bool:
        record.request_id = (
            request_id_context.get()
            or "-"
        )

        return True


def setup_logging() -> None:
    handler = logging.StreamHandler()

    handler.addFilter(
        RequestIDFilter()
    )

    formatter = logging.Formatter(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "request_id=%(request_id)s | "
        "%(message)s"
    )

    handler.setFormatter(formatter)

    root_logger = logging.getLogger()

    root_logger.setLevel(logging.INFO)

    root_logger.handlers.clear()
    root_logger.addHandler(handler)