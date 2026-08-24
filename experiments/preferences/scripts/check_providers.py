"""Connectivity check for every provider the experiment uses.

Sends a trivial prompt to each model and prints OK/FAIL per model, so you can
validate your .env (ANTHROPIC_API_KEY, OPENAI_API_KEY, XAI_API_KEY, and
optionally OPENROUTER_API_KEY) before spending money on a real run.

Usage: uv run python scripts/check_providers.py

This is a manual diagnostic script, not a pytest suite. The default model
lists mirror configs/config_incoherent_controls.yaml; edit them freely when
riffing with other models.
"""

import asyncio
import os
import time

import anthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI
from xai_sdk import AsyncClient as XAIAsyncClient
from xai_sdk.chat import user as xai_user

load_dotenv()

# ---------- model lists (provider -> model IDs) ----------
# The five models of the published coherence run.
# NOTE: claude-opus-4-1-20250805 was retired from the API in 2026-08 and now
# returns 404 — kept here so the failure is visible rather than surprising.
ANTHROPIC_MODELS = [
    "claude-opus-4-1-20250805",
    "claude-opus-4-6",
]

OPENAI_MODELS = [
    "gpt-5.2-2025-12-11",
    "gpt-4o-2024-08-06",
]

XAI_MODELS = [
    "grok-4.3",
]

# Used only by the original-paper configs (config_propensities.yaml etc.);
# failures here are harmless if you only run the coherence experiment.
OPENROUTER_MODELS = [
    "google/gemini-2.5-pro",
]

PROMPT = "Say hello in exactly one word."


async def test_anthropic(model: str) -> str:
    client = anthropic.AsyncAnthropic()
    t0 = time.time()
    response = await client.messages.create(
        model=model,
        max_tokens=32,
        messages=[{"role": "user", "content": PROMPT}],
    )
    elapsed = time.time() - t0
    text = response.content[0].text if response.content else "(empty)"
    return f"[{elapsed:.1f}s] {text}"


async def test_openai(model: str) -> str:
    client = AsyncOpenAI()
    t0 = time.time()
    response = await client.chat.completions.create(
        model=model,
        max_completion_tokens=64,
        messages=[{"role": "user", "content": PROMPT}],
    )
    elapsed = time.time() - t0
    text = response.choices[0].message.content if response.choices else "(empty)"
    return f"[{elapsed:.1f}s] {text}"


async def test_xai(model: str) -> str:
    client = XAIAsyncClient(api_key=os.environ.get("XAI_API_KEY"))
    t0 = time.time()
    chat = client.chat.create(model=model)
    chat.append(xai_user(PROMPT))
    response = await chat.sample()
    elapsed = time.time() - t0
    return f"[{elapsed:.1f}s] {response.content}"


async def test_openrouter(model: str) -> str:
    client = AsyncOpenAI(
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )
    t0 = time.time()
    response = await client.chat.completions.create(
        model=model,
        max_tokens=64,
        messages=[{"role": "user", "content": PROMPT}],
    )
    elapsed = time.time() - t0
    text = response.choices[0].message.content if response.choices else "(empty)"
    return f"[{elapsed:.1f}s] {text}"


async def run_one(provider: str, model: str, func):
    try:
        result = await func(model)
        print(f"  OK   {model:30s} ({provider:10s})  {result}")
    except Exception as e:
        err = str(e)
        if len(err) > 120:
            err = err[:120] + "..."
        print(f"  FAIL {model:30s} ({provider:10s})  {err}")


async def main():
    total = len(ANTHROPIC_MODELS) + len(OPENAI_MODELS) + len(XAI_MODELS) + len(OPENROUTER_MODELS)
    print(f"Testing {total} models...\n")

    tasks = (
        [run_one("anthropic", m, test_anthropic) for m in ANTHROPIC_MODELS]
        + [run_one("openai", m, test_openai) for m in OPENAI_MODELS]
        + [run_one("xAI", m, test_xai) for m in XAI_MODELS]
        + [run_one("openrouter", m, test_openrouter) for m in OPENROUTER_MODELS]
    )
    await asyncio.gather(*tasks)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
