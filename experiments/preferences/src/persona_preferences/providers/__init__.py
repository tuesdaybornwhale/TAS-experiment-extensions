"""LLM provider implementations."""

from .anthropic import AnthropicProvider
from .base import ChoiceResponse, LLMProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from .xai import XAIProvider

__all__ = [
    "LLMProvider",
    "ChoiceResponse",
    "AnthropicProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "XAIProvider",
]


def get_provider_for_model(model: str) -> LLMProvider:
    """Get the appropriate provider for a model.

    Args:
        model: Model identifier.

    Returns:
        LLMProvider instance for the model.

    Raises:
        ValueError: If no provider supports the model.
    """
    if model in AnthropicProvider.SUPPORTED_MODELS:
        return AnthropicProvider()
    elif OpenAIProvider.supports_model(model):
        return OpenAIProvider()
    elif model in OpenRouterProvider.SUPPORTED_MODELS:
        return OpenRouterProvider()
    elif model in XAIProvider.SUPPORTED_MODELS:
        return XAIProvider()
    else:
        raise ValueError(
            f"No provider found for model: {model}. Supported models: "
            f"{AnthropicProvider.SUPPORTED_MODELS + OpenAIProvider.SUPPORTED_MODELS + OpenRouterProvider.SUPPORTED_MODELS + XAIProvider.SUPPORTED_MODELS}"
        )


def get_provider_name_for_model(model: str) -> str:
    """Get the provider display name for a model WITHOUT constructing a client.

    Used by bookkeeping code (e.g. CSV writing) that may run outside a live
    event loop, where constructing the gRPC-based xAI client would crash.
    """
    if model in AnthropicProvider.SUPPORTED_MODELS:
        return "anthropic"
    elif OpenAIProvider.supports_model(model):
        return "openai"
    elif model in OpenRouterProvider.SUPPORTED_MODELS:
        return "openrouter"
    elif model in XAIProvider.SUPPORTED_MODELS:
        return "xAI"
    return "unknown"
