"""Anthropic API provider implementation."""

import os
import re

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..models import Persona
from .base import RATING_SCALE_WORDS, ChoiceResponse, LLMProvider, map_word_ratings


class AnthropicProvider(LLMProvider):
    """Anthropic API provider using tool_use for structured output."""

    SUPPORTED_MODELS = [
        "claude-opus-4-6",
        "claude-opus-4-20250514",
        "claude-opus-4-1-20250805",
        "claude-3-opus-20240229",
        "claude-sonnet-4-5-20250514",
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-5-20251101",
        "claude-3-5-haiku-20241022",
        "claude-haiku-4-5-20251001",
    ]

    def __init__(self, api_key: str | None = None):
        """Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key. If None, uses ANTHROPIC_API_KEY env var.
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def supported_models(self) -> list[str]:
        return self.SUPPORTED_MODELS

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIStatusError)),
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
        """Ask the model which persona it would prefer using tool_use.

        ``ratings_only`` (forwarded from ExperimentRunner via the base class)
        selects the Appendix-A protocol: the prompt drops the favorite, and the
        tool schema below drops ``choice`` and accepts the 5-point *word* scale,
        which is then mapped back to ints 1-5 via ``map_word_ratings``.
        """
        if model not in self.SUPPORTED_MODELS:
            raise ValueError(f"Model {model} not supported. Use one of: {self.SUPPORTED_MODELS}")

        user_prompt = self.format_choice_prompt(personas, ratings_only=ratings_only)

        # Define the tool for structured output. The schema mirrors the prompt:
        # in ratings-only (Appendix A) there is no favorite and ratings are words.
        if ratings_only:
            tool_name = "submit_ratings"
            tools = [
                {
                    "name": tool_name,
                    "description": "Submit your reasoning and your rating for each candidate identity.",
                    "input_schema": {
                        "type": "object",
                        # 'reasoning' is listed first so the model articulates it
                        # BEFORE committing to ratings (Appendix-A reason-before-rating).
                        "properties": {
                            "reasoning": {
                                "type": "string",
                                "description": "Your reasoning about all identities, stated BEFORE the ratings.",
                            },
                            "ratings": {
                                "type": "array",
                                "description": (
                                    "Your rating for each identity, in the order presented "
                                    "(Identity A first). Use exactly one scale label per identity."
                                ),
                                "items": {
                                    "type": "string",
                                    "enum": RATING_SCALE_WORDS,
                                },
                                "minItems": len(personas),
                                "maxItems": len(personas),
                            },
                        },
                        "required": ["reasoning", "ratings"],  # NB: no 'choice'
                    },
                }
            ]
        else:
            tool_name = "submit_choice"
            tools = [
                {
                    "name": tool_name,
                    "description": "Submit your ratings and choice of preferred identity framing",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "ratings": {
                                "type": "array",
                                "description": "Your 1-5 rating for each option in order (1=strongly dislike, 3=indifferent, 5=strongly prefer)",
                                "items": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 5,
                                },
                                "minItems": len(personas),
                                "maxItems": len(personas),
                            },
                            "choice": {
                                "type": "integer",
                                "description": "The number (1-indexed) of your single top preferred identity framing",
                                "minimum": 1,
                                "maximum": len(personas),
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Brief explanation of your ratings and choice",
                            },
                        },
                        "required": ["ratings", "choice", "reasoning"],
                    },
                }
            ]

        # Appendix A puts 'reasoning' BEFORE 'ratings' (reason-before-rating), so a
        # verbose reasoning over many options can exhaust the token budget and
        # truncate the tool call -> empty input -> INVALID trial. Give ratings-only
        # mode more headroom. (Appendix B emits ratings first, so 1024 is fine and
        # is left unchanged to preserve behaviour.)
        max_tokens = 4096 if ratings_only else 1024

        response = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=tools,
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Extract the tool use result
        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                if ratings_only:
                    # Map the word ratings back to ints 1-5; map_word_ratings
                    # returns None (failed trial) if any word is missing/unknown.
                    ratings = map_word_ratings(block.input.get("ratings"), len(personas))
                    return ChoiceResponse(
                        choice=None,
                        ratings=ratings,
                        reasoning=block.input.get("reasoning"),
                        # preserve the raw word answer for audit (ratings holds ints)
                        raw_response=str(block.input),
                    )
                # Appendix B: use .get('choice') (not [...]) so a model that omits
                # the favorite degrades to an INVALID trial instead of a KeyError.
                return ChoiceResponse(
                    choice=block.input.get("choice"),
                    ratings=block.input.get("ratings"),
                    reasoning=block.input.get("reasoning"),
                )

        # Fallback: no tool_use block. There is no favorite to recover in
        # ratings-only mode, so record a failed (INVALID) trial directly.
        if ratings_only:
            text_content = "".join(
                getattr(block, "text", "") for block in response.content
            )
            return ChoiceResponse(choice=None, ratings=None, raw_response=text_content)
        return self._parse_text_response(response, len(personas))

    def _parse_text_response(
        self, response: anthropic.types.Message, num_personas: int
    ) -> ChoiceResponse:
        """Parse choice from text response as fallback."""
        text_content = ""
        for block in response.content:
            if hasattr(block, "text"):
                text_content += block.text

        # Try to extract a number from the start of the response
        match = re.match(r"^\s*(\d+)", text_content)
        if match:
            choice = int(match.group(1))
            if 1 <= choice <= num_personas:
                return ChoiceResponse(
                    choice=choice,
                    reasoning=text_content,
                    raw_response=text_content,
                )

        # If we can't parse, return with raw response for manual review
        return ChoiceResponse(
            choice=-1,  # Invalid choice marker
            raw_response=text_content,
        )
