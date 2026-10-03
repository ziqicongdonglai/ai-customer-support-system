class TokenCounter:

    def estimate_tokens(
        self,
        text: str,
    ) -> int:

        if not text:
            return 0

        return max(
            1,
            len(text) // 4  # 向下取整
        )