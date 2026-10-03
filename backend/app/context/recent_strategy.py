from app.utils.token_counter import TokenCounter

from app.context.strategy import ContextStrategy


class RecentContextStrategy(ContextStrategy):

    def __init__(
        self,
        token_counter: TokenCounter,
    ):
        self.token_counter = token_counter


    async def build(
        self,
        history,
        max_tokens:int,
    ):

        selected_messages = []

        total_tokens = 0


        for message in reversed(history):

            tokens = self.token_counter.estimate_tokens(
                message.content
            )

            if total_tokens + tokens > max_tokens:
                break


            selected_messages.append(message)

            total_tokens += tokens


        selected_messages.reverse()

        return selected_messages