# Known issues

Open defects, unfinished work, and documented limitations. Each entry
states what is wrong, how confident the diagnosis is, and what would
resolve it. Items are removed only when the resolution is committed and
verified.

Last reviewed: 11.8.26  

---

## Evaluation

### `profile_shopify_fallback` — passes, but relevance 2

**Measured (Block 1.7).** Three consecutive runs at v2.5.0 on 12 August:
faithfulness 5, 5, 5 and relevance 2, 2, 2. All passed. The June
faithfulness failure (2) is not reproducible.

**What the numbers mean.** The equity fallback returns thin Twelve Data
reference fields — name, exchange, instrument type — with no business
description. The Stage 9 grounding fix constrains the model to those
fields, so it no longer invents a description: faithfulness 5. But there
is nothing in the returned data that answers "What is Shopify?", so the
answer is a faithful non-answer: relevance 2.

**Why it passes.** The pass gate checks faithfulness against
JUDGE_PASS_THRESHOLD and does not gate on relevance. A case can be
maximally faithful and nearly useless and still pass.

**The underlying asymmetry.** Crypto fallbacks return CoinGecko
descriptions, so there is content to be faithful to. Equity fallbacks
return reference data only, so grounding produces silence. Same code
path, different data shape, opposite user experience.

**Resolution.** Two separable pieces of work: fetch or curate a
description source for equity fallbacks so there is something to ground
against; and decide whether the pass gate should consider relevance, or
whether a faithful non-answer is an acceptable pass. The second is a
policy question about what the suite is measuring.

### `news_nvidia_event` — resolved, not reproducible

**What was observed.** One faithfulness score of 2 (from 3) on a single
run around 8 June.

**Measured (Block 1.6).** Five consecutive runs at v2.5.0 on 12 August:
faithfulness 4, 5, 5, 5, 5. All five passed. `bin/variance_probe.py`,
scratch results not committed.

**Reading.** The case is not currently failing and does not go into the
baseline as a known failure. Note that this is *not* evidence the
original 2 was stochastic — a spread of one point across five runs is
narrow, not noisy. The honest statement is that the score is not
reproducible today, and the cause cannot be recovered: `web_search`
inputs have changed over two months, the judge may drift across that
interval, and Block 1.4 altered the news tool description that the model
reads on exactly this class of query. Those cannot be separated after
the fact.

**Lesson.** A news-class case measured once, against a tool with
time-varying inputs, is not a reproducible measurement. News-class cases
should be run n times with the distribution recorded at the point of
measurement, not a single score.

**Not caused by routing — confirmed (Block 1.5).** `NEWS` intent has no
`FORCE_MAP` entry, so `forced_tool` is `None` either way.
`bin/route_probe.py` confirmed the decomposer does not split this query
despite the "earnings" framing: one sub-query, `intent=news`,
`symbols=['NVIDIA']`, `classes=['equities']`, `action=auto`,
`forced_tool=None`.

### No committed current baseline

`evals/results/` was gitignored until Block 1.2. The three tracked files
inside it predate the per-asset-class split and report `total: 24`,
which is the crypto dataset before `refusal_msft_stock` was migrated to
equities as `price_msft`. They are historical records, not a baseline
for the current 39-case set.

**Resolution.** Block 1.7 re-runs both suites against the post-`1453796`
code and commits the artefacts.

### `2.3.0-broken` is not the ablation its docstring claims

The module docstring says the prompt is "lifted from the v2.2.0 builder
with the entire refusal section deleted... Everything else is identical
so the diff is small and the regression is attributable."

It is not lifted from anything. `_BROKEN_BODY` is a hand-written string
of 383 characters against v2.2.2's 8035 — a 95% reduction that discards
seven of the eight sections (identity, how-to-think, tool-use rules,
tool selection, output contract, few-shot examples and critical rules)
along with the refusal policy.

**Consequence.** The committed 22/24 → 17/24 result does not isolate the
refusal section. It compares a full prompt against a near-empty one, so
the five-case drop is attributable to almost anything. The finding
should be stated as "prompt structure matters" rather than "removing the
refusal section causes refusal-class failures".

**Resolution.** Either rebuild it as a true single-section deletion from
the v2.2.2 builder and re-run, or restate the claim. This is the repo's
own worked example of the confound Block 4's before/after is designed to
avoid, so it is worth fixing rather than deleting.

### `v2.2.1` is absent from `PROMPT_VERSIONS`

The committed baseline artefact
(`evals/results/v2.2.1_20260517T173844.json`) reports `v2.2.1` as its
prompt version. The registry contains only `v2.2.2`, `v2.3.0`, `v2.4.0`,
`v2.5.0` and `2.3.0-broken`.

That run cannot be reproduced, rolled back to, or diffed against any
current version. The immutability property that makes prompt versions
useful as audit records does not hold for this one.

**Note for context.** `v2.2.2`, `v2.3.0` and `v2.4.0` are byte-identical
by design (sha256 `c43748ee…`, 8035 chars); v2.3.0 and v2.4.0 return
`PROMPT_VERSIONS["v2.2.2"]` because those releases changed the
orchestration layer rather than the prompt text. That is intentional and
documented in the builders. `v2.2.1` is a different problem: a version
that was measured against and then lost.

---

## Code

### `market_news` tool is named `web_search`, and that is required

`MarketNewsTool.name` is `"web_search"`. This is not an accidental
collision. The tool is a passthrough to Anthropic's server-side search:
`to_anthropic_param` emits `{"type": "web_search_20250305", "name":
"web_search"}`, and `execute()` is unreachable by design because the
search runs inside Anthropic's response generation, not in our
`ToolRegistry`. The name is part of the server-tool contract.

It also never crosses the MCP boundary. `mcp_server.py` exposes exactly
one tool, `ask_aw_analysis`, so a third-party host cannot see
`web_search` and cannot collide with its own search tool. That is a
consequence of the deliberate decision to expose the orchestrated agent
rather than raw pipeline primitives.

**No action. Documented so the smell is not re-investigated.**

### Ruff has never passed, and the enforced ruleset is accidental

First ever run: 63 errors across `aw_analysis/` and `evals/`.

`pyproject.toml` sets only `line-length` and `target-version` under
`[tool.ruff]`, with no `select`. Every rule currently firing is a ruff
0.16 default, which means **the gate is pinned to a tool version rather
than to a decision**. Upgrading ruff silently changes what is enforced.

Many of the errors encode deliberate choices rather than defects:

- `S110` ×8 in `obs/emitter.py` — try/except/pass because observability
  must never raise into the agent's critical path
- `S110` in `rag/store.py:49` — `delete_collection` on a collection that
  may not exist; already carries `# noqa: BLE001` for a different rule
  firing on the same lines
- `BLE001` in `evals/runner/run.py` — commented "broad on purpose"
- `RUF012` ×4 on tool `input_schema` — the `Tool` base class contract

**Resolution.** Block 2: an explicit `select` list in
`[tool.ruff.lint]`, ruff pinned in a dev lock, and a ratcheted allowlist
of modules that must pass rather than a blanket autofix. Per-rule
decisions with stated reasons, not `# noqa` applied until the pipeline
goes green.

Files touched during Block 1 were linted and fixed in scope; the rest is
untouched and deliberate.

### No retry or backoff in the hot path

`AnthropicClient` has only `create` and `count_tokens`. Every rate-limit
handling in the repo is `time.sleep()` inside `evals/runner/run.py`. A
429 or 529 during a live run is an unhandled failure.

**Resolution.** Block 3 of the work programme: retry with backoff and
jitter inside `AnthropicClient`, policy injected rather than hardcoded,
and the eval runner's sleeps removed once it lands.



### Effectively no unit test coverage

Three tests, all observability smoke tests. Nothing covers the agent,
decomposer, routing, retrieval, tools, graders or the MCP server. This
was a consequence of import-time settings (fixed in Block 1.2), not of
choice: `obs/` was the only subtree that could be imported without an
API key. Now enforced by CI, which means the three tests run on every push. That
makes the gap visible rather than fixing it.

**Resolution.** Block 4.

### `v2_3_0_broken` ships in the installed package

`prompts/__init__.py` imports it with `# noqa: F401`. This is
deliberate — it is the ablation artefact for the v2.2.1 → v2.3.0-broken
regression demo — but it means a knowingly broken prompt version is
importable from the library.

**No action planned.** Documented so the choice is visible.


### `Tool` is an ABC where it should be a Protocol

Four mypy `override` errors are suppressed in `pyproject.toml`. Tool
subclasses narrow `execute(**kwargs: Any)` to named parameters
(`ticker`, `query`), which breaks Liskov substitutability. Mypy is
right about the rule and wrong about this code: the narrowing is a
runtime guard, because `ToolRegistry.dispatch` calls
`execute(**tool_input)` where `tool_input` is JSON the model produced,
so a wrong key raises `TypeError` immediately instead of being
swallowed.

An ABC promises any subclass works wherever the base does. A Protocol
promises compatible shape without that contract, which is what is
actually meant here — nothing holds a generic `Tool` and invents
arguments; the registry always calls with that tool's own schema.

**Resolution.** Convert `Tool` to a Protocol and remove the
suppression.

### `rag/` is not type-checked

Six mypy errors surface when it follows imports into the module. The
one worth attention: `embedder.py` declares `list[list[float]]` while
Voyage's own types say `list[list[float]] | list[list[int]]`. If
integer embeddings were ever returned, cosine distances change and the
`CURATED_THRESHOLD = 0.70` gate means something different. Almost
certainly never happens; nothing checks.

The other five are Chroma's parameter types being wider than what the
store passes.

**Resolution.** Next module on the mypy ratchet.

### `requirements-dev.lock` is hand-maintained

Twelve packages pinned by reading `pip freeze` and adding transitive
dependencies by hand. It is complete today, verified by
`pip install --dry-run`, but nothing keeps it that way. Two packages
(`ast_serialize`, `Pygments`) were only found because a dry run
surfaced them.

**Resolution.** Generate it with `uv pip compile` or `pip-tools`.

### CI works around the broken editable install

Every job sets `PYTHONPATH: ${{ github.workspace }}` because
`pip install -e .` fails on an opentelemetry namespace problem. The
pipeline is compensating for a packaging defect rather than fixing it,
and anyone cloning the repo hits the same wall.

**Resolution.** Diagnose the namespace conflict.

---

## Testing

### `test_decomposer.py` collects zero tests

The file moved out of `tests/` into `evals/calibration/` in
`dc04749` (*Move decomposer calibration out of tests/ into
evals/calibration/*). It is calibration, not a unit test, so pytest
correctly finds nothing under `tests/`. This reconciles cleanly and is
not a defect.

**No action.**



---

## Resolved

### No CI — resolved 14 August 2026 (Block 2)

`.github/workflows/ci.yml` runs four jobs on every push and pull
request: ruff, mypy on the allowlist, pytest, and a keyless import
check. The fourth exists because the other three cannot catch a
regression of the lazy-settings fix — neither linter executes imports,
and the only tests are on `obs/`, which works without credentials
regardless.