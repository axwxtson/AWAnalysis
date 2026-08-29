# v2.7.0 ablation: isolating the Block 6 routing regression

Ran 27 August 2026. Offline analysis, live probe turns.

Companion to `v2.6.0_btc_routing_probe.md`, which established the
regression and its cause. This file records the controlled test of the
fix and states what the result does and does not license.

## The defect under test

`v2.6.0` widened two clauses that together decide when the model should
answer from parametric knowledge instead of calling
`lookup_asset_profile`. Both sites are pinned as constants in
`aw_analysis/prompts/system.py:609-610`:

- `_SCOPE_SUBJECT_V2_6_0 = "a general market, trading or asset concept"`
- `_NO_TOOL_LIST_V2_6_0 = "general market, trading and asset concepts"`

The word `asset` was added to the suppression branch of a system whose
retrieval target is asset profiles. `lookup_asset_profile` stopped
firing on "What is Bitcoin?".

## Design

Two candidates, each differing from `v2.6.0` in exactly one respect.

`cand-a` (`system.py:625`) strikes `asset` at both sites and changes
nothing else. The residual category list, "market and trading", and the
appended product sentence both stand.

`cand-b` (`system.py:640`) reverts the No-tool category list to
`v2.5.0`'s wording, "general concepts". The scope subject keeps `asset`,
so this candidate carries no over-refusal exposure on the subject limb.

Both are derived from `_build_v2_6_0()` by `_substitute_once`, which
raises on a miss. This matters. `str.replace` returning its input
unchanged would register a candidate byte-identical to its own control,
and the ablation would be silently vacuous while appearing to run. The
single-difference constraint therefore holds structurally, not
clerically.

## Arms

Twenty probe turns, ten per candidate, plus a fresh five-turn control on
`v2.6.0`. Query held constant at "What is Bitcoin?". Raw captures
committed alongside this file; each begins with the prompt digest of the
string actually sent.

| arm | digest | turns | `lookup_asset_profile` fired | capture |
|---|---|---|---|---|
| cand-a | `2be3bd50…` | 10 | 10 | `block7_probe_cand_a.txt` |
| cand-b | `76b1615e…` | 10 | 10 | `block7_probe_cand_b.txt` |
| v2.6.0 control | `a6eac9ce…` | 5 | 1 | `block7_probe_v2_6_0_control.txt` |

`cand-a`'s digest is identical to `v2.7.0`'s, because `v2.7.0` aliases
`cand-a` rather than re-deriving it. Editing `cand-a` moves what ships.
Two tests guard this.

## What the statistics license

Fisher's exact, one-sided, on `cand-a` against three different controls.

| comparison | table | p | status |
|---|---|---|---|
| all v2.5.0-era observations | 13/13 v 2/7 | 0.0014 | **retired** |
| same code state | 10/10 v 2/7 | 0.0034 | working figure |
| same code and same harness | 10/10 v 2/5 | 0.0220 | conservative |
| fresh control alone | 10/10 v 1/5 | 0.0037 | independent |
| pooled controls | 10/10 v 3/12 | 0.00044 | post-hoc, not quoted |

Quote 0.0034 as the working figure and 0.0220 under pressure. The
pooling was chosen after the fresh control landed, so it is post-hoc and
is recorded here only so it cannot be presented later as if it were
pre-specified.

0.0014 is retired because its thirteen observations spanned four code
and prompt states rather than one. See the amendment in
`v2.6.0_btc_routing_probe.md`.

## Attribution

`cand-a` restores routing fully while leaving "market and trading"
standing. So the residual widening is not doing the work, and the word
alone is sufficient to explain the regression.

`cand-b` removes the word plus the surrounding list and lands
identically, which is what the word hypothesis predicts. It does not
discriminate between the two on its own; its value is that a
disagreement between the arms would have falsified the reading.

## Named limits

A null result under `cand-a` would have refuted the word and not the
widening. The design was capable of that outcome and it did not occur.

The appended product sentence survives byte-identically in both arms.
Neither candidate can exonerate it. What the result gives is a bound: a
prompt containing that sentence routes 10 in 10, so the sentence is not
sufficient on its own to suppress the call. That is more than the design
promised and less than an ablation of it.

The probe measures one query on one tool. It is not a suite result and
does not speak to any other case.

## Promotion

`v2.7.0` aliases `cand-a`, promoted after suite confirmation on 27
August 2026: crypto 22/23, equities 15/16, general 6/6. Both suite
failures were investigated and are recorded as measured; neither is
attributable to this change. See `KNOWN_ISSUES.md`.