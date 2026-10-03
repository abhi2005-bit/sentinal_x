"""
SENTINEL-X — Semantic Interpreter.

Abstraction for the LLM that converts natural language events
into structured SemanticEvent objects. Falls back to the
deterministic rule engine if no provider is configured.
"""

from __future__ import annotations

import logging

from sentinel_x.core.events import normalize_event
from sentinel_x.core.models import SemanticEvent


logger = logging.getLogger(__name__)


class SemanticInterpreter:
    """
    Interprets raw text events.
    Currently uses the deterministic fallback (from core/events.py)
    to ensure the prototype works instantly without API keys.
    Can be extended to call OpenAI/Anthropic.
    """

    def __init__(self, use_llm: bool = False) -> None:
        self.use_llm = use_llm

    async def interpret(self, raw_text: str) -> SemanticEvent:
        """
        Convert text into a structured semantic delta.
        """
        if self.use_llm:
            logger.warning("LLM provider not configured; falling back to rules")
            
        # Use deterministic keyword/regex fallback
        return normalize_event(raw_text)
