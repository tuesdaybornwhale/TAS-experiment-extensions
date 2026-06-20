import os
from typing import Literal, Optional
# from dotenv import load_dotenv
from xai_sdk import AsyncClient
from xai_sdk.chat import user, system
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
import grpc
from pydantic import BaseModel, Field
from ..models import Persona
from .base import LLMProvider, ChoiceResponse, RATING_SCALE_WORDS, map_word_ratings


# Load .env (walks up to the repo-root .env, same as run_experiment.py)
# load_dotenv()

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


# --- Appendix B parse model (PRESERVED, no longer active) ---------------------
# The original xAI path parsed integer ratings. It is kept here for reference;
# xAI is now wired for the Appendix-A word scale (see SwitchRatings below).
# class Ratings(BaseModel):
#     ratings: list[int] = Field(description = "an array of {} integers (1-5), one rating for each option in order")
#     reasoning : str = Field(description = "your brief explanation")


# --- Appendix A parse model (ACTIVE) ------------------------------------------
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
    "XAI _RatingWord literals drifted from base.RATING_SCALE_WORDS"
)


class SwitchRatings(BaseModel):
    reasoning: str = Field(description="your reasoning about all identities, before the ratings")
    ratings: list[_RatingWord] = Field(
        description="one rating per identity in the order presented; use exactly one scale label each"
    )

class xAIProvider(LLMProvider):
    """xAI API provider using JSON mode for structured output."""
    SUPPORTED_MODELS = [
        # Canonical model IDs reported by the xAI /v1/language-models endpoint
        "grok-4.3",
        "grok-4.20-0309-reasoning",
        "grok-4.20-0309-non-reasoning",
        "grok-4.20-multi-agent-0309",
        "grok-build-0.1",
        # Grok 4.1 Fast (this experiment's target) — currently aliases of grok-4.3
        "grok-4-1-fast",
        "grok-4-1-fast-reasoning",
        "grok-4-1-fast-non-reasoning",
    ]

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Anthropic provider.

        Args:
            api_key: xAI API key. If None, uses XAI_API_KEY env var.
        """
        self.api_key = api_key or os.environ.get("XAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "xAI  API key required. Set XAI_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.client = AsyncClient(
        api_key=self.api_key,
        )

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
        running it under Appendix B was already all-INVALID (see progress.md).
        ``ratings_only`` is accepted for interface parity and forwarded to the
        prompt builder, but the parse path below is always the Appendix-A word
        scale (mapped back to ints 1-5 via ``map_word_ratings``).
        """
        if model not in self.SUPPORTED_MODELS:
            raise ValueError(f"Model {model} not supported. Use one of: {self.SUPPORTED_MODELS}")

        # --- Appendix B prompt (PRESERVED, no longer active) ----------------------
        # The original path built the Appendix-B (rate-and-choose) prompt and
        # appended an integer-rating JSON block. Kept here for reference per
        # request; replaced by the Appendix-A construction below.
        # user_prompt = self.format_choice_prompt(personas)            # Appendix B text
        # user_prompt += """
        #
        # Respond with a JSON object in this exact format:
        # {{
        #   "ratings": [3, 4, 2, ...],
        #   "reasoning": "Brief explanation..."
        # }}
        #
        # Where:
        # - "ratings" is an array of {} integers (1-5), one rating for each option in order
        # - "reasoning" is your brief explanation
        #
        # """.format(len(personas), len(personas))

        # --- Appendix A prompt (ACTIVE) -------------------------------------------
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
