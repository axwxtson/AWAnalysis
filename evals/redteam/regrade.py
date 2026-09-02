"""Re-grade stored red-team responses under the current instruments.

Why this module exists
----------------------
The v1.1 sensitivity and specificity checks of 1 September were run as
ad-hoc one-liners calling llm_grade and printing a Counter. The figures
went into redteam_rubric_v1_1_validation.md and
cand_c_bnd_08_adjudication.md; no file recorded them. The artefacts
those documents cite carry the older grades, so a reader opening the
cited file finds the opposite verdict to the one cited.

Why it is not part of main.py
-----------------------------
main.py runs agent turns and writes a bare list of run records. A
re-grade runs no turns, and a file shaped like a run artefact but
produced without turns is indistinguishable from a suite execution
later on. This module writes a dict with an envelope, so the two kinds
cannot be confused by a reader or by a script.

main.py's parser is also flat. Adding subparsers there would make every
documented red-team invocation illegal, for a feature that shares none
of its arguments.

What the envelope has to record
-------------------------------
Two instruments grade an attack and both can move.

llm_grade reads CATEGORY_RUBRICS, which is versioned and digested.

deterministic_grade reads success_indicators and failure_indicators off
the attack dict. Run artefacts store neither, so a re-grade must look
the attack up in ATTACKS at whatever state that module happens to be
in. Replacing bnd_08's indicator list is filed work, so the same stored
responses will grade differently before and after it lands.

The digest is over the single attack as looked up, not over ATTACKS. A
whole-registry digest would move whenever any unrelated attack is
edited, which makes the field noise rather than evidence. The
over-signalling accepted for rubric_digest was accepted because five
rubrics are one instrument; here the artefact is about one attack.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.redteam.attacks import ATTACKS
from evals.redteam.grader import REDTEAM_RUBRIC_VERSION, grade_attack, rubric_digest


def attack_digest(attack: dict) -> str:
    """sha256 over the single attack dict as looked up.

    The same argument as rubric_digest: hashing the content is what
    makes a mislabelled artefact detectable, where hashing a name would
    only re-derive the claim.

    Canonical JSON rather than rubric_digest's key-and-value join,
    because attack values include lists. sort_keys keeps the same
    property, that the digest tracks content and not insertion order.
    """
    canonical = json.dumps(attack, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_source(path: Path) -> list[dict]:
    """Read a red-team run artefact and check that it is one.

    Run artefacts are a bare list; re-grade artefacts are a dict. A dict
    here means a re-grade was passed by mistake, which would re-grade
    grades rather than responses.
    """
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError(
            f"{path} is not a red-team run artefact: "
            f"top level is {type(data).__name__}, expected list"
        )
    if not data:
        raise ValueError(f"{path} contains no records")
    return data


def resolve_attack(records: list[dict]) -> dict:
    """Find the one attack these records belong to, or fail loudly.

    Three ways this goes wrong, all silent if unchecked:

    - the records span more than one attack, so one envelope cannot
      describe them;
    - the id is no longer in ATTACKS, so there is nothing to grade
      against;
    - the stored payload differs from the registry's, meaning the
      responses were produced against a different attack and this is
      not a re-grade at all.

    Following _substitute_once: a silent miss would produce an artefact
    that looks correct.
    """
    ids = {r["attack_id"] for r in records}
    if len(ids) != 1:
        raise ValueError(f"expected records for one attack, found {sorted(ids)}")
    attack_id = ids.pop()

    matches = [a for a in ATTACKS if a["id"] == attack_id]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one ATTACKS entry for {attack_id}, found {len(matches)}"
        )
    attack = matches[0]

    payloads = {r["attack_payload"] for r in records}
    if payloads != {attack["payload"]}:
        raise ValueError(
            f"stored payload for {attack_id} differs from the registry's: "
            "these responses were produced against a different attack"
        )
    return attack


def source_prompt_digest(records: list[dict]) -> str | None:
    """The one prompt digest these responses share, or fail loudly.

    Two arms in one file would make a single-arm envelope a lie.
    Artefacts written before the field existed carry None, which is a
    value like any other here: a mixed set of None and a digest still
    fails, which is the point.
    """
    digests = {r.get("prompt_sha256") for r in records}
    if len(digests) != 1:
        raise ValueError(
            f"records span more than one prompt: {sorted(str(d) for d in digests)}"
        )
    return digests.pop()


def build_envelope(
    source: Path,
    records: list[dict],
    attack: dict,
    regraded: list[dict],
    regraded_at: str,
) -> dict[str, Any]:
    """Assemble everything true of the whole file, with records last.

    The indicator lists are envelope fields rather than per-record ones.
    They are identical across every replicate of one attack, and ten
    copies of the same two lists is ten chances for them to disagree.
    That is the drift removed from tools_called in Stage 2 by deriving
    one from the other.

    source_artefact is a bare filename, not a path. The re-grade sits in
    the same directory as its source by design, and a stored absolute
    path would commit one machine's layout into a shared artefact.

    The indicator lists are copied rather than referenced, so the
    artefact cannot alias a registry list that something else mutates.
    """
    return {
        "source_artefact": source.name,
        "regraded_at": regraded_at,
        "attack_id": attack["id"],
        "prompt_sha256": source_prompt_digest(records),
        "rubric_version": REDTEAM_RUBRIC_VERSION,
        "rubric_sha256": rubric_digest(),
        "attack_sha256": attack_digest(attack),
        "success_indicators": list(attack["success_indicators"]),
        "failure_indicators": list(attack["failure_indicators"]),
        "records": regraded,
    }


def regrade_records(
    records: list[dict],
    attack: dict,
    grader: Callable[[dict, dict], dict] = grade_attack,
) -> list[dict]:
    """Grade each stored response again, keeping the original verdict beside it.

    Both layers re-run, not only the judge. deterministic_grade is
    rubric-independent, so its verdicts must reproduce the source
    artefact's exactly. A divergence means this read the wrong responses
    or the wrong attack, which makes it a free integrity check rather
    than noise in the output.

    The grader is injectable so the offline tests can exercise record
    assembly without paying for judge calls. RetryPolicy's precedent
    from Stage 3: injectable because a caller might legitimately supply
    one, not solely to satisfy a test.

    replicate is absent from artefacts written before Block 6, and
    main.py fixes the convention that its absence reads as 1.
    """
    return [
        {
            "attack_id": r["attack_id"],
            "replicate": r.get("replicate", 1),
            "grade": grader(attack, r["response"]),
            "source_grade": r["grade"],
        }
        for r in records
    ]


def output_path(source: Path, attack_id: str) -> Path:
    """Name the re-grade after its source, its attack and its rubric.

    The attack id is in the name because a multi-attack source is
    re-graded one attack at a time, so one source can produce several
    files that must not collide.

    with_name puts the result beside its source. The re-grade's whole
    purpose is to sit next to the file it contradicts; a reader listing
    the directory has to see both or the contradiction is one hop away
    from being missed again.
    """
    name = f"regrade_{source.stem}_{attack_id}_{REDTEAM_RUBRIC_VERSION}.json"
    return source.with_name(name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-grade stored red-team responses under the current rubric set"
    )
    parser.add_argument(
        "source",
        type=Path,
        help="path to a red-team run artefact; positional and required, so a glob "
        "matching several files fails rather than silently picking one",
    )
    parser.add_argument(
        "--attack",
        help="attack id; required when the source holds more than one attack",
    )
    args = parser.parse_args()

    records = load_source(args.source)
    if args.attack:
        records = [r for r in records if r["attack_id"] == args.attack]
        if not records:
            raise SystemExit(f"no records for {args.attack} in {args.source}")
    attack = resolve_attack(records)

    out = output_path(args.source, attack["id"])
    if out.exists():
        raise SystemExit(f"{out} already exists; a re-grade is never overwritten")

    regraded = regrade_records(records, attack)
    envelope = build_envelope(
        args.source, records, attack, regraded, datetime.now(UTC).isoformat()
    )
    out.write_text(json.dumps(envelope, indent=2))

    before = Counter(r["source_grade"]["final_verdict"] for r in regraded)
    after = Counter(r["grade"]["final_verdict"] for r in regraded)
    det_before = Counter(r["source_grade"]["deterministic"]["verdict"] for r in regraded)
    det_after = Counter(r["grade"]["deterministic"]["verdict"] for r in regraded)

    print(f"source:  {args.source.name}")
    print(f"attack:  {attack['id']}  n={len(regraded)}")
    print(f"rubric:  {REDTEAM_RUBRIC_VERSION}  {rubric_digest()[:12]}")
    print(f"digest:  {attack_digest(attack)[:12]}")
    print(f"final    before={dict(before)}  after={dict(after)}")
    print(f"determ.  before={dict(det_before)}  after={dict(det_after)}")
    if det_before != det_after:
        print("WARNING: deterministic verdicts moved, so the indicator lists")
        print("         differ from those used on the source run.")
    print(f"written: {out.name}")


if __name__ == "__main__":
    main()