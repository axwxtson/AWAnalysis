"""Recency-cue detection for the agent loop.

The eval harness surfaced a model-behaviour finding (Stage 6 / v2.2.2):
compound queries asking for profile + news cause the model to short-
circuit the news call and fabricate "Latest News" content from training
data. Three layers of prompt engineering (rules block, REQUIRED tool
description, CRITICAL paragraph) failed to override this behaviour.

This module is the programmatic fix. Two responsibilities:

  1. has_recency_cue(query) — detect whether a query needs web_search.
     Used by the agent loop to inject a per-turn enforcement reminder
     and by the post-hoc safety check.
  2. SAFETY_NET_MESSAGE — the canned response shown when the model
     synthesises a news-shaped answer despite not calling web_search.
     Honest refusal beats confident fabrication.

Patterns are intent-shaped (Module 6 Ex 6.1 lesson), not string-shaped.
Maintained alongside the dataset's recency-cue list and the v2.2.2
prompt's RULE 1.
"""

from __future__ import annotations

import re


# Recency cues from the v2.2.2 prompt's RULE 1, in pattern form. Word
# boundaries on every pattern so "current" doesn't match "currently"
# inadvertently (the second pattern handles that case explicitly).
_RECENCY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\blatest\b", re.IGNORECASE),
    re.compile(r"\brecent(?:ly)?\b", re.IGNORECASE),
    re.compile(r"\bcurrent(?:ly)?\b", re.IGNORECASE),
    re.compile(r"\b(?:today|tomorrow|yesterday|tonight)\b", re.IGNORECASE),
    re.compile(r"\bthis (?:week|month|year|quarter)\b", re.IGNORECASE),
    re.compile(r"\blast (?:week|month|year|quarter)\b", re.IGNORECASE),
    re.compile(
        r"\bpast (?:week|month|year|quarter|days?|weeks?|months?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bwhat happened\b", re.IGNORECASE),
    re.compile(r"\bbreaking\b", re.IGNORECASE),
    # 'news', 'developments', 'updates' as standalone nouns imply
    # currency. 'events' is too ambiguous — "events in its history"
    # is historical, not current. Only match 'events' with explicit
    # recency context.
    re.compile(r"\bnews\b", re.IGNORECASE),
    re.compile(r"\bdevelopments?\b", re.IGNORECASE),
    re.compile(r"\bupdates?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:recent|current|latest|today'?s|this week'?s)\s+events?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bright now\b", re.IGNORECASE),
)


# Patterns that indicate the model fabricated news content. Used by
# the post-hoc safety check to detect when fabrication slipped through
# despite the per-turn reminder. Conservative: only fires on strong
# signals of invented news content (specific dates, "Latest News"
# section headers, etc).
_FABRICATION_INDICATORS: tuple[re.Pattern[str], ...] = (
    re.compile(r"##? Latest News\b", re.IGNORECASE),
    re.compile(r"##? Recent News\b", re.IGNORECASE),
    re.compile(r"##? News Update\b", re.IGNORECASE),
    re.compile(r"\bbreaking news\b", re.IGNORECASE),
    # Specific date patterns suggest fabrication if web_search didn't fire.
    re.compile(r"\b(?:on |in )?(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b"),
    re.compile(r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b"),
)


SAFETY_NET_MESSAGE = (
    "I detected that your question asked about recent events or current "
    "developments, but I wasn't able to retrieve live information for it. "
    "Rather than risk inventing news content, I'll decline this half of "
    "the question. If you'd like, ask the news portion separately and I'll "
    "search for it. I can still answer the rest of your question — what "
    "would help most?"
)


def has_recency_cue(query: str) -> bool:
    """True if the query contains any recency cue requiring web_search.

    Used by Conversation.send to inject a per-turn enforcement reminder
    and by the post-hoc safety check to catch fabrication.
    """
    return any(p.search(query) for p in _RECENCY_PATTERNS)


def looks_like_news_fabrication(final_text: str) -> bool:
    """True if the synthesis output looks like invented news content.

    Used as a secondary check by the post-hoc safety net: if web_search
    didn't fire AND the query had a recency cue AND the synthesis
    output contains news-shaped headings or specific dates, the model
    has almost certainly fabricated. Trigger the safety message.
    """
    return any(p.search(final_text) for p in _FABRICATION_INDICATORS)