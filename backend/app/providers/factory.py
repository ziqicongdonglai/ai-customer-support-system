from app.core.exceptions import UnsupportedProviderException
from app.providers.base import BaseLLMProvider
from app.providers.deepseek import DeepSeekProvider
from app.providers.mock import MockProvider

class ProviderFactory:

    @staticmethod
    def create(provider_name: str) -> BaseLLMProvider:
        normalized_name = provider_name.strip().lower()

        if normalized_name == "deepseek":
            return DeepSeekProvider()
        
        if normalized_name == "mock":
            return MockProvider()

        raise UnsupportedProviderException(
            f"Unsupported LLM provider: {provider_name}"
        )