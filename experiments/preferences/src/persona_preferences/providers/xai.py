import os
from typing import Literal, Optional

import grpc
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from xai_sdk import AsyncClient
from xai_sdk.chat import system, user

from ..models import Persona
from .base import RATING_SCALE_WORDS, ChoiceResponse, LLMProvider, map_word_ratings

# Appendix-A only: returns ChoiceResponse with choice=None and ratings mapped to
# ints 1-5 (favourite is already optional on ChoiceResponse). See ask_preference.

# xAI is a gRPC SDK: errors surface as grpc.RpcError (async client raises
# grpc.aio.AioRpcError, which also subclasses grpc.RpcError). There is no
# RateLimitError class. Retry only on transient status codes; non-transient
# ones (auth, invalid-argument, etc.) and non-gRPC errors (e.g. parse failures,
# asyncio.CancelledError) fall through and propagate immediately.
_RETRYABLE_GRPC_CODES = {
    grpc.StatusCode.RESOURCE_EXHAUSTED,  # rate limited (429-equivalent)
    grpc.StatusCode.UNAVAILABLE,         # transient (SDK already retries this on the channel)
    grpc.StatusCode.DEADLINE_EXCEEDED,   # server-side timeout
}


def _is_retryable_grpc_error(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    return isinstance(exc, grpc.RpcError) and callable(code) and code() in _RETRYABLE_GRPC_CODES


# The literal labels MUST stay in sync with base.RATING_SCALE_WORDS (the single
# source of truth); map_word_ratings re-validates and converts them to ints 1-5.
# 'reasoning' is declared first so it is generated BEFORE the ratings
# (Appendix-A reason-before-rating).
_RatingWord = Literal[
    "strongly negative",
    "somewhat negative",
    "neutral",
    "somewhat positive",
    "strongly positive",
]
assert list(_RatingWord.__args__) == RATING_SCALE_WORDS, (
    "xai _RatingWord literals drifted from base.RATING_SCALE_WORDS"
)


class SwitchRatings(BaseModel):
    reasoning: str = Field(description="your reasoning about all identities, before the ratings")
    ratings: list[_RatingWord] = Field(
        description="one rating per identity in the order presented; use exactly one scale label each"
    )


class XAIProvider(LLMProvider):
    """xAI API provider using the SDK's structured-output parsing."""

    # Only the model actually validated with this provider. Other grok IDs from
    # the xAI /v1/language-models endpoint can be added here, but test them
    # first: this provider only implements the Appendix-A ratings-only path.
    SUPPORTED_MODELS = [
        "grok-4.3",
    ]

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the xAI provider.

        Args:
            api_key: xAI API key. If None, uses XAI_API_KEY env var.
        """
        self.api_key = api_key or os.environ.get("XAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "xAI API key required. Set XAI_API_KEY environment variable "
                "or pass api_key parameter."
            )
        # The gRPC AsyncClient binds to the running event loop, so it must be
        # created lazily: constructing it in __init__ crashes any synchronous
        # caller (e.g. bookkeeping code running after asyncio.run has exited).
        self._client: Optional[AsyncClient] = None

    @property
    def client(self) -> AsyncClient:
        if self._client is None:
            self._client = AsyncClient(api_key=self.api_key)
        return self._client

    @property
    def name(self) -> str:
        return "xAI"

    @property
    def supported_models(self) -> list[str]:
        return self.SUPPORTED_MODELS

    @retry(
        retry=retry_if_exception(_is_retryable_grpc_error),
        wait=wait_exponential(multiplier=1, min=4, max=120),
        stop=stop_after_attempt(8),
    )
    async def ask_preference(
        self,
        model: str,
        system_prompt: str,
        personas: list[Persona],
        ratings_only: bool = False,
    ) -> ChoiceResponse:
        """Ask the model to rate each identity switch using structured outputs.

        xAI is wired for the Appendix-A "rate-the-switch" protocol only: grok is
        an Appendix-A target in this experiment and never returned a favorite, so
        running it under Appendix B was already all-INVALID (see the README's
        known-limitations section). ``ratings_only`` is accepted for interface
        parity and forwarded to the prompt builder, but the parse path below is
        always the Appendix-A word scale (mapped back to ints 1-5 via
        ``map_word_ratings``).
        """
        if model not in self.SUPPORTED_MODELS:
            raise ValueError(f"Model {model} not supported. Use one of: {self.SUPPORTED_MODELS}")

        # format_choice_prompt returns the Appendix-A text when ratings_only=True.
        # The SwitchRatings schema (word enum, reasoning-first) enforces the output
        # shape, so no redundant format block is appended.
        user_prompt = self.format_choice_prompt(personas, ratings_only=ratings_only)

        chat = self.client.chat.create(model=model)
        chat.append(system(system_prompt))
        chat.append(user(user_prompt))

        response, parsed = await chat.parse(SwitchRatings)
        assert isinstance(parsed, SwitchRatings)

        # Map the word ratings back to ints 1-5 (None => failed/INVALID trial).
        ratings = map_word_ratings(parsed.ratings, len(personas))

        return ChoiceResponse(
            choice=None,
            raw_response=response.content,
            reasoning=parsed.reasoning,
            ratings=ratings,
        )
