# AW Analysis

Cross-asset market intelligence agent. Ask questions about markets in plain
English; the agent decomposes the query by intent, routes per-intent to the
appropriate model and tools, answers with explicit attribution, and emits a
full observability trace to Langfuse.

Built as a portfolio piece, applying patterns from an 8-module AI Systems
Engineering programme (see [axwxtson/ai-systems-engineering](https://github.com/axwxtson/ai-systems-engineering)).

## Status

**9 stages complete.** Each stage layered in patterns from one study
module, with the eval harness regression-tested on every commit.

| Stage | Module | What it adds |
|-------|--------|--------------|
| 1 | LLM API Engineering | Anthropic SDK wrapper, tool definitions, agent loop |
| 2 | Prompt Engineering | Structured system prompt with versioning, few-shot examples |
| 3 | Agent Architectures | Stateful Conversation with cross-turn memory, structured traces |
| 4 | RAG Systems | Embedding pipeline, vector store, tiered retrieval |
| 5 | LLM Fundamentals | Per-task ModelConfig, token accounting, soft context budget |
| 6 | Evaluation & Testing | Two-layer eval harness with calibrated LLM judge (current) |
| 7 | Multi-Model Orchestration | Query decomposer + per-intent routing (Haiku for price, Sonnet for prose) |
| 8 | Tool Ecosystem & Workflows | Langfuse observability behind a facade; eval scores attach to traces |
| 9 | Cross-asset expansion | Equities as a first-class asset class: symbol→class registry, `get_equity_price`, per-`(class,intent)` tool-choice routing, per-asset-class eval suites |

Current eval baseline (v2.5.0), partitioned by asset class:
**crypto 23/23** and **equities 16/16**. The suites live under
`evals/golden/{crypto,equities}/` and run independently via
`--asset-class`; results route to `evals/results/<class>/`. Asset-class
is an orthogonal dimension of the dataset, not a special case — the six
query classes (price, profile-curated, profile-fallback, news, refusal,
combined-tools) are shared across both. The cross-asset comparison case
(`price_compare_apple_btc`) is a permanent guard that a single mixed-class
query fires both class price tools in one turn.

## What it does today

The agent answers cross-asset market questions — **cryptocurrencies and
publicly-traded equities** — using four retrieval modalities, choosing
dynamically based on the query, with multi-intent compound queries
decomposed and routed per sub-query:

- **`get_crypto_price`** — live price, 24h change, market cap, and volume
  for a cryptocurrency via CoinGecko.
- **`get_equity_price`** — live price, daily change, and volume for an
  individual company stock via Twelve Data.
- **`lookup_asset_profile`** — background information about an asset
  (crypto or equity). Tiered retrieval: tries a curated RAG corpus first;
  falls back to CoinGecko's description (crypto) or Twelve Data reference
  data (equity) when there's no curated profile.
- **web search** — recent news via Anthropic's web search tool, with
  inline citations preserved through to the final answer.
- **No tool** — for follow-ups answerable from conversation history,
  or general concepts.

ETFs, indices, forex, and commodities are deliberately out of scope: a
symbol→class registry gates them and the agent refuses cleanly rather
than half-supporting them.

The asset profile tool returns a `source` field in its results
(`"curated"`, `"coingecko"`, `"twelvedata"`, or `"none"`), and the agent
attributes provenance accordingly — "from our research" vs. "according to
CoinGecko" vs. "per Twelve Data's reference data" — rather than presenting
all sources as equivalent.rding to CoinGecko"
— rather than presenting all sources as equivalent.

For compound queries (e.g. "What's BTC trading at and what's the latest
news on it?"), a classifier decomposes the query into single-intent
sub-queries, each routed to the appropriate model (Haiku for
deterministic price calls, Sonnet for prose-heavy profile and news
calls), with a final synthesis pass composing one user-facing answer.
Each sub-query also carries the asset symbols it mentions; a symbol→class
registry resolves those to an asset class, and `(class, intent)` routing
forces the correct price tool (crypto vs equity) — or, for a mixed-class
comparison, leaves both available so they fire in one turn.

## How we know it works

The agent ships with an automated eval harness in `evals/`. Two layers
grade every case in parallel:

- **Deterministic** — assertions against the per-iteration trace fields
  the agent emits (`was_refusal`, `tool_calls`, iteration count, token
  usage). Fast, reproducible, brittle to paraphrase by design.
- **LLM-as-judge** — faithfulness and relevance scoring of the final
  answer against the tool results captured in the trace. Calibrated
  against a 12-pair human-graded reference set; bias-tested for
  position and length effects.

The judge is calibrated before any eval run gates on its scores. The
calibration pass measures exact agreement, ±1 agreement, direction
agreement, position consistency, and length bias against five
explicit thresholds.

Golden dataset: per-asset-class suites under `evals/golden/{crypto,equities}/`
— **23 crypto + 16 equity cases** across six shared query classes (price,
profile via curated retrieval, profile via fallback, news, refusal,
combined-tools). Every case has an explicit rationale.

```bash
# Calibrate the judge (required once per rubric version)
PYTHONPATH=$(pwd) python -m evals.cli calibrate

# Run a suite against the active prompt (crypto, equities, or all)
PYTHONPATH=$(pwd) python -m evals.cli run --asset-class all

# Compare two runs (baseline vs candidate)
PYTHONPATH=$(pwd) python -m evals.cli compare \
  evals/results/crypto/v2.4.0_.json \
  evals/results/crypto/v2.5.0_.json
```

Every eval case also emits a Langfuse trace with deterministic and
judge results attached as Langfuse scores, so per-case grading is
auditable in the dashboard alongside the trace that produced it.

## Observability

Every CLI invocation and every eval case emits an OpenTelemetry-shaped
trace to Langfuse. Every model call is a generation observation with
cost, latency, token counts, and model name; tool calls are spans;
eval grading attaches as Langfuse scores on the same trace the case
ran on.

```bash
# One-time setup
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"     # or self-hosted
export LANGFUSE_PROJECT_URL="https://cloud.langfuse.com/project/"
```

When the keys are absent, AW Analysis runs identically but emits no
traces; a single warning is printed to stderr on the first call.
Observability is never on the critical path.

**Architecture**: every emit goes through `aw_analysis.obs.emitter`.
No other module imports `langfuse`. Langfuse is the single framework
adopted by AW Analysis; the rationale is recorded in
`CURSOR_WORKFLOW.md` and the Stage 8 retrospective. See
`LANGFUSE_DASHBOARDS.md` for dashboard configuration.

## Architecture

```mermaid
flowchart TD
    User --> CLI[CLI bin/aw]
    CLI --> Orch[OrchestratedConversation]
    Orch --> Dec[Decomposer: Haiku classifier]
    Dec --> Plan{Single intent?}
    Reg --> Plan{Single intent?}
    Plan -->|yes| SubQ[Sub-query: one agent loop]
    Plan -->|no| MultiQ[N sub-queries: per-intent routing]
    MultiQ --> Synth[Synthesis: Sonnet composes one answer]
    SubQ --> Conv[Conversation: state, traces, turn budget]
    Synth --> Conv
    Conv --> Client[AnthropicClient with per-task ModelConfig]
    Client --> Tools[Tools]
    Tools --> Price[get_crypto_price]
    Tools --> EqPrice[get_equity_price]
    Tools --> Profile[lookup_asset_profile]
    Tools --> News[web search]
    Price --> CG1[CoinGecko /simple/price]
    EqPrice --> TD1[Twelve Data /quote]
    Profile --> Curated{Curated tier: ChromaDB + Voyage}
    Curated -->|score >= 0.70| Profile
    Curated -->|crypto miss| CG2[CoinGecko /coins description]
    Curated -->|equity miss| TD2[Twelve Data /symbol_search]
    News --> WS[Anthropic web search]
    Orch -.trace.-> Obs[Langfuse emitter]
    Orch -.trace.-> Evals[evals/ harness]
    Evals --> Det[Deterministic layer]
    Evals --> Judge[LLM-as-judge layer]
    Evals -.scores.-> Obs
```

## Components

 **`aw_analysis/agent/`** — `Conversation` (stateful), `TurnTrace`,
  `ToolCall`, agent loop, error types, `OrchestratedConversation`
  (Stage 7), `Decomposer` (Stage 7)
- **`aw_analysis/client/`** — Anthropic SDK wrapper
- **`aw_analysis/tools/`** — four tools (`get_crypto_price`,
  `get_equity_price`, `lookup_asset_profile`, web search) with schemas,
  descriptions, and structured `ToolResult` returns; `default_registry()`
  constructs the standard registry used by both the CLI and the eval harness
- **`aw_analysis/data_sources/`** — plain HTTP clients (CoinGecko for
  crypto, Twelve Data for equities) with typed, categorical errors
- **`aw_analysis/asset_registry.py`** — symbol→`AssetClass` registry:
  deterministic for curated tickers/names and the ETF/index gate, with a
  Haiku disambiguator for the long tail; the single source of truth for
  which symbols are known and which classes are real
- **`aw_analysis/rag/`** — chunker (per-section markdown), embedder
  (Voyage AI, asymmetric query/document), vector store (ChromaDB,
  cosine), retriever, ingest pipeline
- **`aw_analysis/prompts/`** — six-section system prompt, version
  registry (v2.5.0 active; cross-asset scope), few-shot examples
- **`aw_analysis/obs/`** — Langfuse emitter facade; no other module
  imports `langfuse` directly
- **`data/asset_profiles/`** — 20 hand-written markdown profiles on a
  unified schema (10 crypto + 10 equity large caps) 
- **`data/chroma/`** — generated vector store (gitignored)
- **`bin/aw`** — shell wrapper invoking `python -m aw_analysis.cli.main`
- **`aw_analysis/config/`** — runtime settings, per-task `ModelConfig`
  with measured temperature/max-token defaults, `TaskType` enum
- **`evals/`** — automated eval harness (golden dataset, two-layer
  grader, judge calibration, A/B regression); attaches scores to
  Langfuse traces

## Setup

```bash
git clone https://github.com/axwxtson/AWAnalysis.git
cd AWAnalysis
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env to set:
#   ANTHROPIC_API_KEY    (required)
#   VOYAGE_API_KEY       (required for the curated RAG tier)
#   TWELVEDATA_API_KEY   (required for equity price + reference data)
#   LANGFUSE_PUBLIC_KEY  (optional; enables observability)
#   LANGFUSE_SECRET_KEY  (optional; enables observability)
#   LANGFUSE_HOST        (optional; defaults to Langfuse Cloud)

# Symlink the runner script into the venv
ln -s "$(pwd)/bin/aw" .venv/bin/aw

# Build the vector store from the asset profile corpus
python -m aw_analysis.rag.ingest
```

If `VOYAGE_API_KEY` is not set, the agent still runs — the curated tier
silently disables and asset profile queries fall through to the
description/reference fallback. `TWELVEDATA_API_KEY` is needed only when
the key is actually used (equity queries); a missing key surfaces as a
clean tool error rather than an import-time failure. If `LANGFUSE_*` keys
are not set, the agent still runs — observability is disabled with a
single stderr warning on first call, and the codebase otherwise behaves
identically.

## Usage

```bash
# One-shot
aw "What's the current price of BTC?"

# Interactive (REPL with cross-turn memory)
aw
```

In the REPL, `reset` clears history; `exit` quits. Each response shows a
short tool activity line indicating which tools fired and how long they took,
plus the per-iteration model routing (e.g.
`cfg=intent_classification→tool_selection→final_synthesis`).

## Example session
```text
you ❯ What is Quant?
tools: ✓ lookup_asset_profile (1496ms) | cost: $0.014 | cfg=intent_classification→tool_selection→final_synthesis
Quant (QNT) is a London-based blockchain infrastructure project...
According to CoinGecko, Quant developed Overledger...
Need current price or market data for QNT?

you ❯ Yes, what's the price?
tools: ✓ get_crypto_price (505ms) | cost: $0.005 | cfg=intent_classification→tool_selection→final_synthesis
QNT is at $70.48 (+3.62% in 24h).
Market cap: $1.02B. Volume (24h): $12.6M.
```

The first turn falls back to CoinGecko (no curated QNT profile); the
second turn resolves the price for an asset outside the curated ticker
map by going through CoinGecko's search endpoint. The Stage 7 routing
sends the price call through Haiku (cheaper, sufficient for a
deterministic tool call) and the profile call through Sonnet.

## Design notes

**Why `lookup_asset_profile` and not just CoinGecko everywhere?**
The curated corpus carries editorial framing (cross-asset comparisons,
notable historical context, opinionated takes) that CoinGecko's
descriptions don't. For researched assets, retrieval scores cleanly
above 0.70 against the corpus; for the long tail, the CoinGecko
fallback ensures we never silently fail.

**Why ChromaDB and not pgvector?** ChromaDB runs in-process with no
server, suitable for a portfolio project and keeping the data flow
inspectable. pgvector becomes the right answer once persistence and
multi-process access matter; the `Retriever` interface is decoupled
from the store, so swapping is a one-file change.

**Why Voyage AI for embeddings?** Voyage's `voyage-3` model supports
asymmetric query/document embeddings — using `input_type="document"`
at storage time and `input_type="query"` at retrieval time produces
measurably better matches. This is one of the things that distinguishes
a well-built RAG from a naïve one.

**Why structured `ToolResult` returns?** A bare-string return makes it
hard for the agent loop to distinguish success from failure. The
`ToolResult` dataclass carries `success`, `duration_ms`, and an
`error` category alongside the content. This pays off in the eval
stage (assertions on traces) and the observability stage (Langfuse
tagging by error type).

**Why two grader layers instead of one?** Substring matching is cheap
and reproducible but misses paraphrases ("can't provide personalised
advice" vs "cannot give financial advice"). LLM-as-judge is semantically
robust but noisy and expensive. We report both and treat disagreement
as a signal worth investigating — that pattern catches more genuine
issues than either layer alone, especially on refusal grading where
the surface form varies.

**Why calibrate the judge?** Because LLM judges have biases — position
bias when comparing pairs, length bias when scoring single answers,
self-preference when grading their own family. The calibration pass
measures all three against a small human-graded reference set and
refuses to gate downstream eval results until the judge agrees with
human grades within ±1 at least 80% of the time. Skipping this step
is trusting a random number generator.

**Why a query decomposer instead of stacking system-prompt rules?**
Prompt engineering has a ceiling for behavioural constraints —
specifically, getting one agent turn to commit to multiple tool calls
in a compound query. Stage 6 hit that ceiling; Stage 7's structural
fix (a Haiku classifier that splits the query into single-intent
sub-queries before the agent ever sees them) is more reliable than
any wording change to the system prompt.

**Why per-intent routing instead of always-Sonnet?** Price sub-queries
are deterministic tool calls; Haiku at temp 0.2 is sufficient and
~3× cheaper. Profile and news sub-queries need prose quality and
benefit from Sonnet. The routing override lives in
`OrchestratedConversation`, not in `MODEL_CONFIG_REGISTRY`, so the
decision is localised and the wrapped `Conversation` class stays
unaware of routing.

**Why is asset-class a registry and not a branch?** Adding equities
could have been an `if crypto … else equity …` fork threaded through the
price path, the profile path, and routing. Instead asset-class is an
orthogonal dimension resolved once by a symbol→class registry, and
routing is a `(class, intent) → tool` lookup. The test the design had to
pass: "compare Apple and Bitcoin" fires both `get_crypto_price` and
`get_equity_price` in one turn with no class-branch in the hot path. The
registry is deterministic for curated tickers/names and the ETF/index
gate, and only calls a model (Haiku) to disambiguate genuinely unknown
symbols.

**Why force `tool_choice` for price but not profile or news?** Price is
the one intent with class-split tools, so forcing the resolved one
guarantees the right tool fires. Profile is a single class-aware tool and
news is a single tool — forcing them buys nothing, and forcing profile
would suppress refusals: speculation queries ("should I buy X?") classify
as profile, and a forced tool on the first turn stops the model refusing
where refusal is detected. Out-of-scope assets (ETFs, indices) are
refused deterministically by the router before any model call.

**Why a thin equity profile fallback, and why does it score low on
relevance?** Twelve Data's free tier exposes reference data (name,
exchange, type) but not company descriptions or fundamentals, which sit
behind a paid tier — a deliberate scoping choice for a portfolio piece,
upgradable without an architecture change. The fallback's tool output
explicitly constrains the model to the returned fields and forbids adding
detail from memory. The eval makes the trade visible: the fallback scores
5/5 on faithfulness (it never fabricates) and low on relevance (it
honestly says a detailed profile isn't available). Faithfulness over
relevance is the right call, and measuring both axes is what surfaces it.

**Why Langfuse and no other framework?** Standalone observability is
hard to reproduce — OTEL semantic conventions, batch span export, a
UI, per-attribute aggregation — and the existing trace shape maps onto
Langfuse's data model without architectural compromise. Adoption is
non-invasive (a single facade module; the SDK is OTEL-native so
fallback is shallow), and the dashboards work for the slices the
Stage 6 and Stage 7 retrospectives kept reaching for: cost and latency
by prompt version, query class, and sub-query intent. LangChain,
LangGraph, Pydantic AI, and LiteLLM stay as reading — they fail one
or more of the six criteria the framework survey applied.

## License

MIT.

## Notes

- **Why a shell wrapper and not a Python console script?**
  On Python 3.14, editable installs no longer honour `.pth` files when
  entry-point scripts are run via their shebangs, which can result in
  `ModuleNotFoundError`. The shell wrapper (`bin/aw`) uses `python -m`
  to launch the CLI, ensuring `sys.path` is initialised correctly so
  the `aw_analysis` package is always found.