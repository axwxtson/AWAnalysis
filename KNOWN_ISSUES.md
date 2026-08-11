# Known issues

Open defects, unfinished work, and documented limitations. Each entry
states what is wrong, how confident the diagnosis is, and what would
resolve it. Items are removed only when the resolution is committed and
verified.

Last reviewed: 11.8.26  

---

## Evaluation

### `profile_shopify_fallback` — faithfulness 2 (expected 5)

**What happens.** The equity profile fallback path returns thin Twelve
Data reference fields (name, exchange, type). The model appends a
business description for Shopify that is not present in the returned
data.

**Diagnosis (confident).** Training-data gravity on a well-known name.
This is the same failure Stage 9 already fixed once for Oracle in
`fix(profile): ground the equity fallback to its reference fields` —
the grounding language constrains the model to the returned fields, and
it holds for Oracle but not for a larger-cap name where the prior is
stronger.

**Not caused by routing.** `FORCE_MAP` contains only `(CRYPTO, PRICE)`
and `(EQUITIES, PRICE)`. This case is `PROFILE` intent, so
`decide_route` returns `AUTO` and `forced_tool` is `None`. The one-line
fix in `1453796` forwards `forced_tool` to `_run_loop`; when it is
`None` the post-fix call is identical to the pre-fix call. The fix is a
provable no-op here. To be confirmed empirically in Block 1.5.

**Resolution.** Extend the Oracle grounding fix to hold on high-prior
names. Likely a structural rather than directive change, since the
directive already exists.

### `news_nvidia_event` — faithfulness 3 → 2 on one run

**What happens.** One observed drop in the faithfulness score.

**Diagnosis (provisional).** Probably run-to-run variance. `web_search`
returns different results on each call, so the `news` class has
non-deterministic inputs by construction. The Stage 9 retrospective
already records `news` faithfulness around 3.5 as expected and
explicitly says not to tune it away. A single 3 → 2 move is not
evidence of a regression.

**Not caused by routing.** Same argument as above: `NEWS` intent has no
`FORCE_MAP` entry, so `forced_tool` is `None` either way.

**Resolution.** Block 1.6 runs the case three to five times and records
the spread. If 2 sits inside the observed range, this entry closes as
expected variance rather than a defect.

### No committed current baseline

`evals/results/` was gitignored until Block 1.2. The three tracked files
inside it predate the per-asset-class split and report `total: 24`,
which is the crypto dataset before `refusal_msft_stock` was migrated to
equities as `price_msft`. They are historical records, not a baseline
for the current 39-case set.

**Resolution.** Block 1.7 re-runs both suites against the post-`1453796`
code and commits the artefacts.

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

### No retry or backoff in the hot path

`AnthropicClient` has only `create` and `count_tokens`. Every rate-limit
handling in the repo is `time.sleep()` inside `evals/runner/run.py`. A
429 or 529 during a live run is an unhandled failure.

**Resolution.** Block 3 of the work programme: retry with backoff and
jitter inside `AnthropicClient`, policy injected rather than hardcoded,
and the eval runner's sleeps removed once it lands.

### No CI

There is no `.github/` directory. Ruff, mypy and pytest all run
manually.

**Resolution.** Block 2.

### Effectively no unit test coverage

Three tests, all observability smoke tests. Nothing covers the agent,
decomposer, routing, retrieval, tools, graders or the MCP server. This
was a consequence of import-time settings (fixed in Block 1.2), not of
choice: `obs/` was the only subtree that could be imported without an
API key.

**Resolution.** Block 4.

### `v2_3_0_broken` ships in the installed package

`prompts/__init__.py` imports it with `# noqa: F401`. This is
deliberate — it is the ablation artefact for the v2.2.1 → v2.3.0-broken
regression demo — but it means a knowingly broken prompt version is
importable from the library.

**No action planned.** Documented so the choice is visible.

---

## Testing

### `test_decomposer.py` collects zero tests

The file moved out of `tests/` into `evals/calibration/` in
`dc04749` (*Move decomposer calibration out of tests/ into
evals/calibration/*). It is calibration, not a unit test, so pytest
correctly finds nothing under `tests/`. This reconciles cleanly and is
not a defect.

**No action.**