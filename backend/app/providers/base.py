from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator


# 只向编排层暴露不可变的 Provider 中立事件，避免上层依赖 DeepSeek 原始协议。
# frozen=True 表示创建以后不允许再改。
@dataclass(frozen=True)
class ContentDelta:
    text: str


@dataclass(frozen=True)
class ToolCallComplete:
    id: str
    name: str
    arguments: dict


ToolStreamEvent = ContentDelta | ToolCallComplete


class BaseLLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
    ) -> str:
        """
        Send a chat request with conversation history
        and return the complete response.
        """
        raise NotImplementedError
    
    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[str, None]:# AsyncGenerator[产生的数据类型, 发送的数据类型]
        """
        Send a streaming chat request with conversation history
        and yield response chunks.
        """
        raise NotImplementedError

    @abstractmethod
    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str,
    ) -> AsyncGenerator[ToolStreamEvent, None]:
        """Stream content or return one complete, provider-neutral Tool Call."""
        raise NotImplementedError
