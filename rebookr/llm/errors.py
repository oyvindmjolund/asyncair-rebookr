"""Normalised errors. The router only ever sees these, never vendor exceptions."""


class LLMError(Exception):
    """Base class. `retryable` tells the router whether to try somewhere else."""
    retryable = False

    def __init__(self, provider: str, message: str):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


class ProviderUnavailable(LLMError):
    """5xx, overloaded, connection refused, timeout. Try another provider."""
    retryable = True


class RateLimited(LLMError):
    """429. Try another provider (or wait)."""
    retryable = True


class BadRequest(LLMError):
    """4xx that is *our* fault. Falling back will not help - fix the request."""
    retryable = False


class CapabilityMissing(LLMError):
    """The provider/model can't do what the request needs (e.g. vision)."""
    retryable = True


class StreamInterrupted(LLMError):
    """The provider died *after* we had already shown text to the user."""
    retryable = False


class AllProvidersFailed(Exception):
    def __init__(self, route: str, errors: list[str]):
        super().__init__(f"Route '{route}': every provider failed -> " + " | ".join(errors))
        self.errors = errors
