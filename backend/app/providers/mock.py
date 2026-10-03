import asyncio
import json
import logging
import re
from typing import AsyncGenerator

from app.core.exceptions import ProviderException
from app.providers.base import BaseLLMProvider, ContentDelta, ToolCallComplete, ToolStreamEvent


logger = logging.getLogger(__name__)


class MockProvider(
    BaseLLMProvider
):
    """Mock LLM provider for local development and testing."""

    async def chat(
        self,
        messages: list[dict],
    ) -> str:

        logger.info(
            "Mock provider received chat request"
        )

        return "Mock response"


    async def stream_chat(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[str, None]:

        logger.info(
            "Mock provider received streaming request"
        )

        tool_result = next(
            (message.get("content") for message in reversed(messages)
             if message.get("role") == "tool"),
            None,
        )
        if tool_result and json.loads(tool_result).get("action") == "return_eligibility":
            chunks = [
                "I've prepared the return eligibility check. ",
                "Click Start check and choose the purchase to continue.",
            ]
        else:
            chunks = [
                "Mock ",
                "streaming: ",
                f"received {len(messages)} messages",
            ]

        for chunk in chunks:
            await asyncio.sleep(0.5)
            # yield 暂停当前函数，并返回一个中间结果，下次继续从暂停的位置执行。
            yield chunk

    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str,
    ) -> AsyncGenerator[ToolStreamEvent, None]:
        user_text = next(
            (message.get("content", "") for message in reversed(messages)
             if message.get("role") == "user"),
            "",
        )
        # 严格的 Mock-only fixture：ChatService 已先建立 Conversation/start，随后
        # Provider 失败并映射为 SSE 1001；精确短语避免演变成通用 fault injection。
        if user_text == "force stream error after start":
            raise ProviderException("Forced Mock Provider stream failure")

        shipment_id = re.search(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            user_text,
        )
        if shipment_id and "shipment" in user_text.lower():
            yield ToolCallComplete(
                id="mock-tool-call-1",
                name="get_shipment_status",
                arguments={"shipment_id": shipment_id.group(0)},
            )
            return

        if "can i return" in user_text.lower() or "return eligibility" in user_text.lower():
            yield ToolCallComplete(
                id="mock-tool-call-2",
                name="request_return_eligibility_check",
                arguments={},
            )
            return

        for text in ("Mock ", "streaming: ", f"received {len(messages)} messages"):
            yield ContentDelta(text)
