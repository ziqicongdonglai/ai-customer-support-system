from abc import ABC, abstractmethod


class ContextStrategy(ABC):

    @abstractmethod
    async def build(
        self,
        history,
        max_tokens:int,
    ):
        pass