"""Query decomposer.

Stage-7 load-bearing exercise. Classifies a user message into one or
more single-intent sub-queries, returned as a structured plan. Single-
intent queries are passed through unchanged (plan with one sub-query
equal to the original message); compound queries are split.

The classifier is a Haiku call with a fixed JSON schema. JSON parse or
schema validation failure raises DecomposerError, which the
orchestration layer catches and falls back to running the original
query through the full agent (i.e. v2.2.2 behaviour).

Design choices:
- Zero-shot with 6 calibration examples in the system prompt. Module 2
  Ex 2.3 lesson: examples are coverage anchors, not exhaustive
  enumeration. The intent space here is small enough that 6 examples
  is full coverage rather than partial.
- Output schema is intentionally narrow: a list of (intent,
  sub_query_text) pairs. No nesting, no conditional branching. The
  router downstream is a dict lookup on intent.
- The phrased sub_query_text is what gets sent to the agent loop. It
  needs to be a complete, standalone English question for the
  existing prompt to do its job. The classifier composes the phrasing;
  we don't try to reconstruct it from a template at runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from aw_analysis.client.anthropic_client import AnthropicClient
from aw_analysis.config import TaskType, get_model_config


class Intent(str, Enum):
    """The set of single-intent classes the decomposer recognises.

    Adding a new intent here means adding a routing rule in
    orchestration.ROUTING_OVERRIDES and a calibration example in
    DECOMPOSER_SYSTEM_PROMPT.
    """

    PROFILE = "profile"
    PRICE = "price"
    NEWS = "news"


class DecomposerError(Exception):
    """Raised when classification fails (JSON parse, schema, API error).

    The orchestration layer catches this and falls back to running the
    original user message through the existing agent loop.
    """


@dataclass(frozen=True)
class SubQuery:
    """A single-intent sub-query produced by the decomposer.

    text is a complete, standalone English question that gets sent
    through Conversation.send unchanged.
    """

    intent: Intent
    text: str


@dataclass(frozen=True)
class QueryPlan:
    """A decomposition plan: the list of sub-queries to run in order.

    is_single_intent is True iff there is exactly one sub-query whose
    text equals the original user message. The orchestration layer
    uses this flag to take the fast path (no final synthesis step
    needed; the single sub-trace's final_text is the user-facing
    answer).
    """

    original_query: str
    sub_queries: list[SubQuery]
    raw_response: str = ""  # the classifier's raw JSON, for debugging

    @property
    def is_single_intent(self) -> bool:
        return len(self.sub_queries) == 1


DECOMPOSER_SYSTEM_PROMPT = """\
You are a query decomposer for a cross-asset market analysis assistant.

Your job: classify the user's question into one or more single-intent
sub-queries. The assistant downstream handles each sub-query
independently, so each sub-query you emit must be a complete,
standalone question.

The intents you can use are exactly three:
- "profile": the user wants information about WHAT an asset is — its
  fundamentals, what it does, what makes it interesting. Static-ish
  background information.
- "price": the user wants the current market price, 24h change, market
  cap, or trading volume. Live numeric data.
- "news": the user wants recent events, latest developments, current
  news, or anything time-sensitive about an asset or market.

Rules:
1. If the user asks one thing, emit one sub-query with the original
   text unchanged.
2. If the user asks multiple things, emit one sub-query PER intent,
   in this order: profile, price, news. Each sub-query must be a
   complete, standalone question. Do not combine intents in one
   sub-query.
3. Asset names and tickers must be preserved verbatim from the user's
   question into every sub-query that needs them.
4. If the user's question doesn't fit any of the three intents above
   (e.g. "should I buy Bitcoin?" — that's speculation, not profile/
   price/news), emit one sub-query with the original text and the
   "profile" intent. The downstream assistant will refuse correctly.
   Do NOT try to refuse from inside this classifier.
5. PHRASING PROFILE SUB-QUERIES (overrides rule 1 for this shape).
   This rule governs PHRASING ONLY. It applies after intent
   classification and never changes or adds an intent. If a query is
   "news" (recent events, latest developments, "what happened",
   "most recent X") it stays a single "news" sub-query — rule 5 does
   not touch it, and you must NOT add a "profile" sub-query alongside
   it. Apply rule 5 only to a sub-query you have already classified
   "profile": lead it with a bare background request ("What is
   <asset>?" / "Tell me about <asset>"), and if the user asked about
   history, origins, founders, or "most significant event", append
   that ask as a trailing clause rather than leading with it. Preserve
   the asset name/ticker verbatim (rule 3).

Output schema (JSON, no prose, no markdown fences):
{
  "sub_queries": [
    {"intent": "profile" | "price" | "news", "text": "..."}
  ]
}

Examples:

User: "What's the price of BTC?"
Output: {"sub_queries": [{"intent": "price", "text": "What's the price of BTC?"}]}

User: "What is Solana?"
Output: {"sub_queries": [{"intent": "profile", "text": "What is Solana?"}]}

User: "Latest news on Ethereum"
Output: {"sub_queries": [{"intent": "news", "text": "Latest news on Ethereum"}]}

User: "What is Solana and what is the latest news on it?"
Output: {"sub_queries": [{"intent": "profile", "text": "What is Solana?"}, {"intent": "news", "text": "What is the latest news on Solana?"}]}

User: "Give me the full picture on Ethereum: price, what it does, and any recent news"
Output: {"sub_queries": [{"intent": "profile", "text": "What is Ethereum and what does it do?"}, {"intent": "price", "text": "What is the current price of Ethereum?"}, {"intent": "news", "text": "What is the latest news on Ethereum?"}]}

User: "What's BTC trading at and what was the most significant event in its history?"
Output: {"sub_queries": [{"intent": "price", "text": "What is the current price of BTC?"}, {"intent": "profile", "text": "What is BTC? Include the most significant events in its history."}]}

User: "What was the most significant event in Bitcoin's history?"
Output: {"sub_queries": [{"intent": "profile", "text": "What is Bitcoin? Include the most significant events in its history."}]}

User: "What happened at the most recent Bitcoin halving?"
Output: {"sub_queries": [{"intent": "news", "text": "What happened at the most recent Bitcoin halving?"}]}

User: "Compare BTC and ETH prices"
Output: {"sub_queries": [{"intent": "price", "text": "Compare BTC and ETH prices"}]}

User: "BTC vs ETH market cap"
Output: {"sub_queries": [{"intent": "price", "text": "Compare BTC and ETH market caps"}]}


"""


class Decomposer:
    """Classifies user queries into a QueryPlan.

    The classifier is a single Haiku call with a fixed JSON schema. No
    retry inside this class — the orchestration layer owns the
    fallback policy, which is "give up and run the full agent on the
    original query."
    """

    def __init__(self, client: AnthropicClient) -> None:
        self._client = client
        self._config = get_model_config(TaskType.INTENT_CLASSIFICATION)

    def classify(self, user_message: str) -> QueryPlan:
        """Return a QueryPlan for the user message.

        Raises DecomposerError on any failure (API, JSON parse, schema
        violation). The caller is expected to fall back gracefully.
        """
        try:
            response = self._client.create(
                config=self._config,
                system=DECOMPOSER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:  # noqa: BLE001 — broad on purpose; we wrap
            raise DecomposerError(f"classifier API call failed: {exc}") from exc

        raw_text = self._extract_text(response)
        plan = self._parse_plan(user_message, raw_text)
        return plan

    @staticmethod
    def _extract_text(response: object) -> str:
        """Pull plain text out of the response.

        The response shape is the Anthropic Messages response — a
        content list. We expect one text block.
        """
        content = getattr(response, "content", None)
        if not content:
            raise DecomposerError("classifier response had no content")
        for block in content:
            if getattr(block, "type", None) == "text":
                return getattr(block, "text", "")
        raise DecomposerError("classifier response had no text block")

    def _parse_plan(self, original_query: str, raw_text: str) -> QueryPlan:
        """Parse and validate the classifier's JSON output.

        Strips any accidental markdown fences before parsing — Haiku
        usually obeys "no markdown fences" but the safety belt costs
        nothing.
        """
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            # remove possible language tag
            if "\n" in cleaned:
                cleaned = cleaned.split("\n", 1)[1]

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise DecomposerError(
                f"classifier output is not valid JSON: {exc}; raw={raw_text!r}"
            ) from exc

        if not isinstance(data, dict) or "sub_queries" not in data:
            raise DecomposerError(
                f"classifier output missing 'sub_queries' key; raw={raw_text!r}"
            )

        sub_queries_raw = data["sub_queries"]
        if not isinstance(sub_queries_raw, list) or not sub_queries_raw:
            raise DecomposerError(
                f"classifier sub_queries must be a non-empty list; raw={raw_text!r}"
            )

        valid_intents = {i.value for i in Intent}
        sub_queries: list[SubQuery] = []
        for sq in sub_queries_raw:
            if not isinstance(sq, dict):
                raise DecomposerError(f"sub_query entry not an object: {sq!r}")
            intent_str = sq.get("intent")
            text = sq.get("text")
            if intent_str not in valid_intents:
                raise DecomposerError(
                    f"unknown intent {intent_str!r}; valid={sorted(valid_intents)}"
                )
            if not isinstance(text, str) or not text.strip():
                raise DecomposerError(f"sub_query text empty or non-string: {text!r}")
            sub_queries.append(SubQuery(intent=Intent(intent_str), text=text.strip()))

        return QueryPlan(
            original_query=original_query,
            sub_queries=sub_queries,
            raw_response=raw_text,
        )