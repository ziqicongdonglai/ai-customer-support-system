import httpx
import logging
import time
import json
from collections.abc import AsyncIterable
from typing import AsyncGenerator

from app.core.config import settings
from app.core.exceptions import (
    ConfigurationException,
    ProviderException,
)
from app.providers.base import (
    BaseLLMProvider,
    ContentDelta,
    ToolCallComplete,
    ToolStreamEvent,
)

logger = logging.getLogger(__name__)


class DeepSeekProvider(BaseLLMProvider):
    async def chat(
        self,
        messages: list[dict],
    ) -> str:
        if not settings.deepseek_api_key:
            logger.error(
                "DeepSeek API key is missing"
            )
            raise ConfigurationException(
                "DEEPSEEK_API_KEY is not configured"
            )

        url = f"{settings.deepseek_base_url}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": settings.deepseek_model,
            "messages":messages,
            "stream": False,
        }

        try:
            start_time = time.perf_counter()

            logger.info(
                "Sending request to DeepSeek"
            )
            async with httpx.AsyncClient(
                timeout=settings.request_timeout,
            ) as client:

                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                )

                response.raise_for_status()
                data = response.json()

                elapsed = time.perf_counter() - start_time

                logger.info(
                    "DeepSeek response received in %.2fs",
                    elapsed,
                )

        except httpx.TimeoutException as exc:
            logger.warning(
                "DeepSeek request timeout"
            )

            raise ProviderException(
                "DeepSeek request timed out"
            ) from exc

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code

            logger.error(
                "DeepSeek API returned status %s",
                status_code,
            )

            raise ProviderException(
                f"DeepSeek API returned status {status_code}"
            ) from exc

        except httpx.RequestError as exc:
            logger.error(
                "Failed to connect to DeepSeek API"
            )

            raise ProviderException(
                "Failed to connect to DeepSeek API"
            ) from exc

        return self._extract_content(data)

    async def stream_chat(
        self,
        messages: list[dict],
    ) -> AsyncGenerator[str, None]:

        if not settings.deepseek_api_key:
            logger.error(
                "DeepSeek API key is missing"
            )

            raise ConfigurationException(
                "DEEPSEEK_API_KEY is not configured"
            )

        url = f"{settings.deepseek_base_url}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "stream": True,
        }

        try:
            logger.info(
                "Sending streaming request to DeepSeek"
            )

            async with httpx.AsyncClient(
                timeout=settings.request_timeout,
            ) as client:

                # 打开一个持续读取的响应流。
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                ) as response:

                    response.raise_for_status()

                    # 异步逐行读取 HTTP 响应
                    async for line in response.aiter_lines():

                        # SSE 格式:
                        # data: {"choices":[{"delta":{"content":"hello"}}]}
                        if not line.startswith("data:"):
                            continue
                        # 去掉 SSE 前缀 "data:"
                        # 以及可能存在的空格、换行
                        data = line[5:].strip()

                        # DeepSeek 流结束标记
                        if data == "[DONE]":
                            break

                        if not data:
                            continue

                        logger.debug(
                            "DeepSeek streaming chunk: %s",
                            data,
                        )

                        chunk = json.loads(data)

                        content = (
                            chunk
                            .get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content")
                        )

                        # 只返回最终回答内容
                        # reasoning_content(thinking) 不返回
                        if content:
                            yield content


        except httpx.TimeoutException as exc:

            logger.warning(
                "DeepSeek streaming request timeout"
            )

            raise ProviderException(
                "DeepSeek streaming request timed out"
            ) from exc


        except httpx.HTTPStatusError as exc:

            status_code = exc.response.status_code

            logger.error(
                "DeepSeek streaming API returned status %s",
                status_code,
            )

            raise ProviderException(
                f"DeepSeek streaming API returned status {status_code}"
            ) from exc


        except httpx.RequestError as exc:

            logger.error(
                "Failed to connect to DeepSeek streaming API"
            )

            raise ProviderException(
                "Failed to connect to DeepSeek streaming API"
            ) from exc

    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        tool_choice: str,
    ) -> AsyncGenerator[ToolStreamEvent, None]:
        if not settings.deepseek_api_key:
            raise ConfigurationException(
                "DEEPSEEK_API_KEY is not configured"
            )

        url = f"{settings.deepseek_base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "stream": True,
        }

        async def response_chunks() -> AsyncGenerator[dict, None]:
            async with httpx.AsyncClient(
                timeout=settings.request_timeout,
            ) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        if data:
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError as exc:
                                raise ProviderException(
                                    "DeepSeek returned an invalid streaming response"
                                ) from exc
                            if not isinstance(chunk, dict):
                                raise ProviderException(
                                    "DeepSeek returned an invalid streaming response"
                                )
                            yield chunk

        try:
            async for event in self._translate_tool_chunks(response_chunks()):
                yield event
        except httpx.TimeoutException as exc:
            raise ProviderException(
                "DeepSeek streaming request timed out"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderException(
                f"DeepSeek API returned status {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderException(
                "Failed to connect to DeepSeek streaming API"
            ) from exc

    async def _translate_tool_chunks(
        self,
        chunks: AsyncIterable[dict],
    ) -> AsyncGenerator[ToolStreamEvent, None]:
        # 首个有效数据决定 Direct 或 Tool 路径，Slice 2 不支持两种路径在同一响应中混用。
        state = "undecided"
        tool_id = ""
        tool_name = ""
        argument_fragments: list[str] = []
        tool_complete = False

        async for chunk in chunks:
            try:
                choices = chunk["choices"]
                if (
                    not isinstance(choices, list)
                    or len(choices) != 1
                    or not isinstance(choices[0], dict)
                ):
                    raise ValueError
                choice = choices[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason")
                if not isinstance(delta, dict):
                    raise ValueError
                content = delta.get("content")
                tool_calls = delta.get("tool_calls") or []
                if content is not None and not isinstance(content, str):
                    raise ValueError
                if not isinstance(tool_calls, list):
                    raise ValueError
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderException(
                    "DeepSeek returned an invalid streaming response"
                ) from exc

            # Direct 内容一旦作为 SSE 发出便无法撤回，因此任何混合响应都必须拒绝。
            if tool_complete and (content or tool_calls):
                raise ProviderException("DeepSeek returned mixed Tool content")
            if content and tool_calls:
                raise ProviderException("DeepSeek returned mixed Tool content")

            if content:
                if state == "tool":
                    raise ProviderException("DeepSeek returned mixed Tool content")
                state = "direct"
                yield ContentDelta(content)

            if tool_calls:
                if state == "direct" or len(tool_calls) != 1:
                    raise ProviderException("DeepSeek returned unsupported Tool Calls")
                state = "tool"
                call = tool_calls[0]
                if not isinstance(call, dict) or call.get("index") != 0:
                    raise ProviderException("DeepSeek returned unsupported Tool Calls")
                function = call.get("function") or {}
                if not isinstance(function, dict):
                    raise ProviderException("DeepSeek returned an invalid Tool Call")
                incoming_id = call.get("id")
                incoming_name = function.get("name")
                arguments = function.get("arguments")
                if incoming_id:
                    if not isinstance(incoming_id, str) or (tool_id and tool_id != incoming_id):
                        raise ProviderException("DeepSeek returned an invalid Tool Call")
                    tool_id = incoming_id
                if incoming_name:
                    if not isinstance(incoming_name, str) or (tool_name and tool_name != incoming_name):
                        raise ProviderException("DeepSeek returned an invalid Tool Call")
                    tool_name = incoming_name
                if arguments is not None:
                    if not isinstance(arguments, str):
                        raise ProviderException("DeepSeek returned invalid Tool arguments")
                    # DeepSeek 会跨 chunk 拆分 JSON，必须等 Tool Call 完成后再统一解析。
                    argument_fragments.append(arguments)

            if finish_reason is not None:
                if state == "tool":
                    if finish_reason != "tool_calls" or not tool_id or not tool_name:
                        raise ProviderException("DeepSeek returned an incomplete Tool Call")
                    try:
                        arguments = json.loads("".join(argument_fragments))
                    except json.JSONDecodeError as exc:
                        raise ProviderException(
                            "DeepSeek returned invalid Tool arguments"
                        ) from exc
                    if not isinstance(arguments, dict):
                        raise ProviderException("DeepSeek returned invalid Tool arguments")
                    tool_complete = True
                    yield ToolCallComplete(tool_id, tool_name, arguments)
                elif finish_reason != "stop":
                    raise ProviderException("DeepSeek returned an unsupported finish reason")

        if state == "tool" and not tool_complete:
            raise ProviderException("DeepSeek returned an incomplete Tool Call")
            
            

    def _extract_content(
        self,
        data: dict,
    ) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            logger.error(
                "DeepSeek returned an invalid response structure"
            )

            raise ProviderException(
                "DeepSeek returned an invalid response"
            ) from exc

        if not isinstance(content, str):
            logger.error(
                "DeepSeek returned non-string content"
            )

            raise ProviderException(
                "DeepSeek returned an invalid response"
            )

        return content
