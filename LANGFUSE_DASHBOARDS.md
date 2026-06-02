# Langfuse Dashboard Configuration for AW Analysis

How to set up the Langfuse dashboards that surface AW Analysis's
per-prompt-version, per-query-class, and per-sub-query-intent
metrics.  This is a one-time setup per Langfuse project.

## 0. Prerequisites

- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
  set in your shell (`~/.zshrc`).
- Optional: `LANGFUSE_PROJECT_URL=https://cloud.langfuse.com/project/<id>`
  so the eval JSON contains clickable links.
- At least one CLI invocation completed, so the project has a
  trace to verify against.

## 1. Verify ingestion

In the Langfuse UI, go to **Tracing → Traces**.  Filter by tag
`interface:cli`.  You should see one trace per CLI invocation,
named `aw_analysis.turn`, with nested observations matching the
Stage 8 hierarchy:

```text
aw_analysis.turn
├── decomposer.classify
│   └── classifier-llm-call (generation)
├── sub_query[0]
│   ├── iteration:tool_selection (generation)
│   ├── tool:get_crypto_price (span)
│   └── iteration:final_synthesis (generation)
└── ...
```

If you see only the root span: traces are being created but
nested observations are not being emitted.  Check the Stage 8
emit calls in `orchestration.py`.

## 2. Built-in cost + latency dashboards

Langfuse ships with **Dashboards → Generations** out of the box.
With no configuration, this shows:

- Total cost over time
- Tokens per generation (input / output)
- Latency per generation
- Cost / latency grouped by `model.name`

This works for AW Analysis without any setup because the emitter
populates the standard fields (`usage_details`, `cost_details`,
`model`) on every generation observation.

## 3. Custom dashboard: per-prompt-version metrics

Create a new dashboard called **AW Analysis — Prompt Versions**.

- **Time range:** Last 30 days (adjust as needed).
- **Filter:** `tags contains "interface:eval"` (so the chart
  only shows eval-suite traces, not interactive CLI noise).
- **Widget 1:** "Trace count" grouped by tag `prompt:*`.
- **Widget 2:** "Mean cost per trace" grouped by tag `prompt:*`.
- **Widget 3:** "Mean latency per trace" grouped by tag `prompt:*`.
- **Widget 4:** Scores aggregate: filter by score name
  `case.passed`, show mean value grouped by tag `prompt:*`.

This is the dashboard you screen-share in interviews to answer
*"how do you A/B test prompt changes?"*.

## 4. Custom dashboard: per-query-class metrics

Create a new dashboard called **AW Analysis — Query Classes**.

- **Filter:** `tags contains "interface:eval"`.
- **Group by:** metadata `query.class`.
- **Widgets:** trace count, mean cost, mean latency, mean
  `case.passed` score.

This surfaces the Stage 6 + 7 question "which class is regressing?"
without a JSON diff.

## 5. Custom dashboard: per-sub-query-intent

Create a new dashboard called **AW Analysis — Sub-Query Intents**.

- **Filter:** observations where metadata `sub_query.intent` is
  set (i.e. only sub-query spans, not turn-level traces).
- **Group by:** metadata `sub_query.intent`.
- **Widgets:** count, mean cost, mean latency.

This shows the cost ratio between price (Haiku) and
profile/news (Sonnet) sub-queries — the routing economics from
Stage 7 visualised.

## 6. Scores view

Per-trace, the **Scores** tab shows every score attached to that
trace's case.  For an eval-suite trace you'll see:

- `assertion.<name>` = 1.0 or 0.0 per deterministic check
- `judge.faithfulness`, `judge.relevance`, `judge.refusal_correctness` = 1–5
- `case.passed` = 1.0 or 0.0

Use the **Compare** view (two traces side by side) to inspect
why a case that passed in one run failed in another.

## 7. Smoke check before declaring Stage 8 done

After the build, run:

```bash
PYTHONPATH=$(pwd) python3 -m aw_analysis.cli.main "What is the price of BTC?"
```

In the Langfuse UI within 30 seconds:

1. Open **Tracing → Traces**, filter `interface:cli`.
2. Open the most recent trace.
3. Verify the hierarchy: `aw_analysis.turn → decomposer.classify
   → sub_query[0] → iteration:tool_selection → tool:get_crypto_price
   → iteration:final_synthesis`.
4. Verify the root trace has tags `prompt:v2.3.0` and
   `interface:cli`.
5. Verify each generation has non-zero `cost_details.total` and
   non-empty `model`.

If any of these are missing, the emit call for that observation
is broken — re-read the relevant emit site in `emitter.py`.