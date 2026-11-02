"""Qwen transport and bounded request concurrency."""

import asyncio
import logging
import os
import time
from dotenv import load_dotenv
from openai import AsyncOpenAI

LOGGER = logging.getLogger("src.ai_manager")
RELEVANCE_MODEL = "qwen3.7-flash"
REASONING_MODEL = "qwen3.7-plus"
MAX_CONCURRENT_REQUESTS = 4


class AITransportError(RuntimeError):
    pass


class AIConfigurationError(ValueError):
    pass


def create_client():
    """Create the shared asynchronous Qwen client.

    The API key and compatible endpoint come from the environment. Missing
    configuration raises ``ValueError`` before any module requests are started.
    """
    load_dotenv()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("DASHSCOPE_BASE_URL")
    if not api_key or not base_url:
        raise ValueError("DASHSCOPE_API_KEY and DASHSCOPE_BASE_URL must be configured.")

    return AsyncOpenAI(api_key=api_key, base_url=base_url)


class QwenClient:
    def __init__(self, provider, semaphore=None):
        self.provider = provider
        self.semaphore = semaphore

    async def request(self, model, messages, thinking, task_name, json_mode=False):
        """Send one Qwen request and return its non-empty text response.

        ``semaphore`` enforces the pipeline-wide concurrency limit. Timing starts
        after the semaphore is acquired, so logs measure the HTTP request rather
        than queue time. ``json_mode`` is used only when the provider supports it.
        """
        request = {
            "model": model,
            "messages": messages,
            "extra_body": {"enable_thinking": thinking},
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        if self.semaphore is None:
            self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        async with self.semaphore:
            LOGGER.info("HTTP task started: %s [%s]", task_name, model)
            started_at = time.perf_counter()
            try:
                response = await self.provider.chat.completions.create(**request)
            except Exception as error:
                elapsed_seconds = time.perf_counter() - started_at
                LOGGER.info(
                    "HTTP task failed: %s [%s] after %.2f seconds",
                    task_name,
                    model,
                    elapsed_seconds,
                )
                raise AITransportError(str(error)) from error
            elapsed_seconds = time.perf_counter() - started_at
            LOGGER.info(
                "HTTP task completed: %s [%s] in %.2f seconds",
                task_name,
                model,
                elapsed_seconds,
            )
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError) as error:
            raise ValueError("Model returned no readable content.") from error
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Model returned no readable content.")
        return content.strip()
