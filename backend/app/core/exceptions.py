class AIBackendException(Exception):
    """Base exception for AI backend errors."""
    pass


class ProviderException(AIBackendException):
    """Base exception for provider errors."""
    pass


class ConfigurationException(AIBackendException):
    """Base exception for configuration errors."""
    pass

class UnsupportedProviderException(ConfigurationException):
    """Raised when requested LLM provider is not supported."""
    pass

class NotFoundException(
    AIBackendException
):
    """Base exception for resource not found."""
    pass

class ConversationNotFoundException(
    NotFoundException
):
    pass


class WorkflowUnavailableException(NotFoundException):
    pass


class ActiveWorkflowConflictException(AIBackendException):
    pass


class WorkflowPersistenceConflictException(AIBackendException):
    pass
