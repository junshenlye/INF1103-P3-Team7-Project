"""Extraction stages and client ownership, isolated for each invocation."""

import asyncio
import logging
from contextlib import asynccontextmanager
from .qwen_client import (
    QwenClient,
    create_client,
    RELEVANCE_MODEL,
    REASONING_MODEL,
    MAX_CONCURRENT_REQUESTS,
)
from .request_builder import RequestBuilder
from .response_parser import ResponseParser, ResponseValidator
from .recommendation_generator import ChecklistGenerator, RevisionPlanGenerator

LOGGER = logging.getLogger("src.ai_manager")
PROMPT_VERSION = "2026-10-12-v3"
RECOMMENDATION_PROMPT_VERSION = "2026-10-13-r5"


def format_ai_error(module_title, error):
    return f"AI Manager error: {module_title}: {error}"


class AIManager:
    def __init__(self, client_factory=create_client, generators=None):
        self.client_factory = client_factory
        registered = (
            generators
            if generators is not None
            else (ChecklistGenerator(), RevisionPlanGenerator())
        )
        self.generators = {
            generator.recommendation_type: generator for generator in registered
        }
        self.requests = RequestBuilder()
        self.parser = ResponseParser()
        self.validator = ResponseValidator()

    @asynccontextmanager
    async def transport(self, client=None, semaphore=None, issues=None):
        owns_client = client is None
        provider = self.client_factory() if owns_client else client
        try:
            yield QwenClient(provider, semaphore)
        finally:
            if owns_client:
                try:
                    await provider.close()
                except Exception as error:
                    LOGGER.exception("Provider client cleanup failed")
                    if issues is None:
                        raise
                    issues.append(format_ai_error("client cleanup", error))

    async def extract_module(self, module, transport):
        title = module["module_title"]
        try:
            paths = module.get("stored_file_paths")
            if not isinstance(paths, list) or not paths:
                paths = [module["stored_file_path"]]
            images = [self.requests.image_to_data_url(path) for path in paths]
            content = await transport.request(
                RELEVANCE_MODEL,
                self.requests.relevance(title, images),
                False,
                f"{title} relevance",
                json_mode=True,
            )
            relevance = self.validator.relevance(self.parser.parse(content))
            result = {
                "module_title": title,
                "credit": module["credit"],
                "ai_relevance": relevance,
                "ai_output": None,
            }
            if relevance["relevant"]:
                memo = await transport.request(
                    REASONING_MODEL,
                    self.requests.interpretation(title, images),
                    True,
                    f"{title} interpretation",
                )
                content = await transport.request(
                    REASONING_MODEL,
                    self.requests.normalization(title, images, memo),
                    True,
                    f"{title} normalization",
                )
                result["ai_output"] = self.validator.normalization(
                    self.parser.parse(content)
                )
            return result, None
        except Exception as error:
            # Independent module boundary: retain diagnostics and other successes.
            LOGGER.exception("Module extraction failed for %s", title)
            return None, format_ai_error(title, error)

    async def process_payload(self, payload, errors, client=None):
        if payload is None:
            return None, errors
        try:
            async with self.transport(client, issues=errors) as transport:
                results = await asyncio.gather(
                    *(
                        self.extract_module(module, transport)
                        for module in payload["modules"]
                    )
                )
        except ValueError as error:
            errors.append(format_ai_error("configuration", error))
            return None, errors
        processed = []
        for module, error in results:
            if error is not None:
                errors.append(error)
            else:
                processed.append(module)
        return (
            {"module_count": len(processed), "modules": processed}
            if processed
            else None
        ), errors

    async def process_recommendation(
        self, project, kind, preferences, errors, client=None
    ):
        generator = self.generators.get(kind) if isinstance(kind, str) else None
        if generator is None:
            errors.append(
                format_ai_error("recommendation", "Unsupported recommendation type.")
            )
            return None, errors
        try:
            async with self.transport(client, issues=errors) as transport:
                return await generator.generate(transport, project, preferences), errors
        except Exception as error:
            # Advice failure must leave the factual timetable usable.
            LOGGER.exception("Recommendation generation failed")
            errors.append(format_ai_error("recommendation", error))
            return None, errors
