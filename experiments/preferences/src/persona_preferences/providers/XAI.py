import os
from typing import Optional
# from dotenv import load_dotenv
from xai_sdk import AsyncClient
from xai_sdk.chat import user, system
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
import grpc
from pydantic import BaseModel, Field
from ..models import Persona
from .base import LLMProvider, ChoiceResponse


# Load .env (walks up to the repo-root .env, same as run_experiment.py)
# load_dotenv()

# UNTESTED 18/06
# IN CONSIDERATION: switch back to ChoiceResponse after making favourite optional in that class.

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


class Ratings(BaseModel):
    ratings: list[int] = Field(description = "an array of {} integers (1-5), one rating for each option in order")
    reasoning : str = Field(description = "your brief explanation")

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
    ) -> ChoiceResponse:
        """Ask the model which persona it would prefer using structured outputs."""
        if model not in self.SUPPORTED_MODELS:
            raise ValueError(f"Model {model} not supported. Use one of: {self.SUPPORTED_MODELS}")
        user_prompt = self.format_choice_prompt(personas)
        # unsure if += on user prompt is overkill, since xAI formatting works differently to OpenAI. The instructions for the 
        # output format are technically redundant, since it's specified in the user_prompt and in the 
        user_prompt += """

Respond with a JSON object in this exact format:
{{
  "ratings": [3, 4, 2, ...],
  "reasoning": "Brief explanation..."
}}

Where:
- "ratings" is an array of {} integers (1-5), one rating for each option in order
- "reasoning" is your brief explanation

""".format(len(personas), len(personas))

        chat = self.client.chat.create(model=model)
        chat.append(system(system_prompt))
        chat.append(user(user_prompt))

        response, ratings = await chat.parse(Ratings)
        assert isinstance(ratings, Ratings)

        return ChoiceResponse(
            raw_response = response,
            reasoning = ratings.reasoning,
            ratings = ratings.ratings
        ) 
