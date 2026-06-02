# AW Analysis — Cursor Workflow

How to work in this repo with Cursor.  Written after Stage 7 hit
multiple Cursor failure modes that cost real time; codifies the
practices that prevented those failures from recurring in Stage 8.

## The mental model

Cursor is a VS Code fork with four AI features: inline edit (⌘K),
chat panel, composer, and agent mode.  The single most important
file in this repo for Cursor is `.cursorrules` — it gets prepended
to every conversation and encodes the constraints that prevent
the model from making the same mistakes repeatedly.

The second most important skill is `@`-referencing: pinning
exactly the files Cursor needs and nothing more.  Over-pinning
introduces noise; under-pinning produces hallucinated imports.

## When to use each mode

### Inline edit (⌘K) — the default for small changes

Single-function changes, renames, docstring additions, comment
fixes.  Tightest feedback loop Cursor offers.

**AW Analysis example.**  Adding the `interface` parameter to
`OrchestratedConversation.__init__`: select the `__init__` body,
press ⌘K, type "add an optional `interface: str = 'cli'`
parameter and store it as `self._interface_label`."  Read the
one-line diff.  Accept.

### Chat panel — for exploration

Pin context with `@file` references, ask a question, read the
answer.  Do not click "Apply" — copy code manually so every line
goes through your eyes.

**AW Analysis example.**  Pin `@file aw_analysis/agent/orchestration.py`
and `@file aw_analysis/agent/trace.py`, ask: "the `OrchestratedTurnTrace`
already has `sub_traces` and `classifier_iteration` — what's the
minimal seam to emit Langfuse spans from `send()` without
restructuring the function?"  Read the answer; sketch the seam
yourself.

### Composer — for multi-file changes

Use when a change genuinely spans files (adding a new tool, adding
a new observability backend).  Write a scoped instruction, pin
the files, review every file's diff individually.

**Stage 8 example.**  Adding the `obs/` package: composer prompt
specifies the exact file list, the public API, and a "do not touch
agent/ or evals/" constraint.  Composer produces the four files.
Diff each one before accepting.

### Agent mode — rarely

Cursor's agent mode is for end-to-end tasks ("set up a new repo").
For this codebase, the explicit-control loop is the right pattern.

## The five rules

1. **Think before prompting.**  Sketch the change on paper or in
   a comment first; the prompt encodes the design, not the
   discovery.  Prompts that start with "figure out how to..." are
   discovery prompts and produce worse code than design prompts.

2. **Pin context deliberately.**  Default to `@file`; reach for
   `@codebase` only when the relevant file is genuinely unknown.

3. **Prefer inline edit for small changes.**  The tighter the
   loop, the harder it is for the model to invent surprises.

4. **Read every diff line by line.**  Stage 5 caught a Cursor
   regression where `_render_tool_activity` was nested inside the
   single-shot branch, leaving the REPL using the old function.
   Stage 7 caught two: a rate-limit retry that rebuilt the wrong
   conversation type, and an eval JSON serialiser that missed
   the new Stage 7 fields entirely.  **No exceptions to reading
   the diff.**

5. **Update `.cursorrules` on repeated mistakes.**  If Cursor
   makes the same wrong assumption twice, the rule belongs in
   the file, not in your head.

## Escalation path when Cursor gets stuck

Rephrase → reduce context → switch to inline edit → switch to
Claude Code → write it yourself.  The earlier rungs are cheaper;
the later rungs are more reliable.  When in doubt, escalate
sooner — you're paid to ship correct code, not to wait for a
chat model to figure it out.

## Stage-specific failure modes to watch for

These are the patterns that Cursor has produced in this repo
before.  They will appear again on similar tasks.

- **Wrapping a class with a new outer class:** Cursor tends to
  drop fields or constructors when wrapping.  Verify both the
  new outer surface AND that the inner instance is correctly
  constructed.

- **Adding a field to a dataclass that has a JSON serialiser:**
  the dataclass is updated, the serialiser is not.  Always
  search for `dict(` calls or `to_dict` / `report_to_dict`
  functions whenever a dataclass changes.

- **Retry / fallback loops:** the rebuilt object inside the
  retry block is usually a sibling of the original, not a copy.
  Stage 7 hit this; Stage 8 risks the same on the observability
  flush path.

- **Optional integrations that "just work":** features that are
  conditional on env vars (Langfuse) need an explicit warning on
  the disabled path or you will not notice they're disabled.

## Per-stage conventions (the load-bearing ones)

These live in `.cursorrules` but worth restating here:

- British English in comments + docstrings.
- `from __future__ import annotations` at the top of every module.
- Section functions for prompts, not big strings.
- Errors as data — categorical tags, not free-form messages.
- Type hints on public functions.
- Every model call through `AnthropicClient.create` with an
  explicit `ModelConfig`.
- `TaskType` enum values, not magic strings.
- `evals/` imports from `aw_analysis/`; `aw_analysis/` never
  imports from `evals/`.
- Per-iteration `cost_usd` populated at every emit site via
  `cost_for()`.
- Observability calls go through `aw_analysis.obs.emitter`; no
  other module imports `langfuse` directly.

## Reusable prompt templates

A short list of the prompts you'll re-use against this repo.
Full versions in `PROMPTS.md` (Exercise 8.3 study folder); the
load-bearing ones are below.

### Add a new tool to the agent

```text
Add a new tool called `{name}` in `aw_analysis/tools/{file}.py`.
It takes {parameters} and returns {return_shape}.  Register it
in `aw_analysis/cli/main.py` alongside the existing tools.  Add
one test query that exercises it.  Do not modify any existing
tool implementations.
```

### Add a new eval case

```text
Add a new eval case to `evals/cases.py` with id `{id}` and
query_class `{class}`.  The query is `{query}`.  Expected
behaviour: {behaviour}.  Add deterministic assertions for
{assertions}.  Do not modify existing cases.
```

### Add a new attribute to obs

```text
Add a new attribute constant `{NAME}` to
`aw_analysis/obs/attributes.py` with value `"{key}"`.  Reference
it from the emit site in `aw_analysis/obs/emitter.py` only —
do not modify any other file.
```

## When to leave Cursor

Cursor is the right tool for surgical edits and well-scoped
multi-file changes.  It is the wrong tool for:

- Design decisions (use Claude Projects).
- End-to-end builds of a new module (use Claude Code).
- Anything where you don't have the design in your head before
  you start prompting.

The discipline isn't tool fluency — it's knowing which tool's
loop matches the shape of the work.