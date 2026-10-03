from typing import Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class CommonResponse(BaseModel, Generic[T]):
    code: int
    message: str
    data: T | None = None
    success: bool