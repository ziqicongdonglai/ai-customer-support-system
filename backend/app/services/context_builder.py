from uuid import UUID

from app.core.config import settings
from app.rag.models import RetrievedChunk
from app.context.models import ContextBuildResult


class ContextBuilder:

    def __init__(
        self,
        message_repo,
        strategy,
        token_counter,
    ):
        self.message_repo = message_repo
        self.strategy = strategy
        self.token_counter = token_counter

    async def build(
        self,
        conversation_id: UUID,
        retrieved_chunks: list[RetrievedChunk] | None = None,
        system_suffix: str = "",
    ) -> ContextBuildResult:

        history = await self.message_repo.get_by_conversation_id(
            conversation_id
        )

        current_user = history[-1]
        older_history = history[:-1]

        system_content = settings.default_system_prompt
        if system_suffix:
            system_content += f"\n\n{system_suffix}"

        system_tokens = self.token_counter.estimate_tokens(system_content)

        retrieved_chunks = retrieved_chunks or []

        current_user_tokens = self.token_counter.estimate_tokens(
            current_user.content
        )

        remaining_tokens = max(
            settings.max_context_tokens 
            - system_tokens
            - current_user_tokens,
            0,
        )

        used_chunks: list[RetrievedChunk] = []

        knowledge_block = ""
        
        knowledge_tokens = 0

        # 试放 假设添加后
        for chunk in retrieved_chunks:
            candidate_chunks = used_chunks + [chunk]

            candidate_context = "\n\n".join(
                f"{index + 1}. {item.content}"
                for index, item in enumerate(candidate_chunks)
            )

            candidate_block = (
                "[Knowledge Context]\n"
                "以下是与用户问题相关的检索知识，请在相关时将其作为回答依据：\n\n"
                f"{candidate_context}"
            )

            candidate_tokens = self.token_counter.estimate_tokens(
                candidate_block
            )

            if candidate_tokens > remaining_tokens:
                break

            used_chunks = candidate_chunks
            knowledge_block = candidate_block
            knowledge_tokens = candidate_tokens


        remaining_tokens = max(
            remaining_tokens - knowledge_tokens,
            0,
        )

        selected_messages = await self.strategy.build(
            older_history,
            remaining_tokens,
        )

        if knowledge_block:
            system_content += f"\n\n{knowledge_block}"

        messages = [
            {
                "role": "system",
                "content": system_content,
            }
        ]

        messages.extend(
            [
                {
                    "role":item.role,
                    "content":item.content,
                }
                for item in selected_messages
            ]
        )

        messages.append(
            {
                "role": current_user.role,
                "content": current_user.content,
            }
        )

        return ContextBuildResult(
            messages=messages,
            used_chunks=used_chunks,
        )
