"""Assertions about the graph the engine STORED, not the one the source declares.

`run export` is the only surface that hands back the canonical projection the
engine accepted and froze for a run. The human renderer prints its digest, and a
digest is not what needs checking -- the topology is, and so is the vocabulary
the published guidance uses to describe it.

Both modes print flat lines so the shell harness can assert on them with plain
substring matching rather than parsing.
"""

import json
import re
import sys

# Tokens in the guidance that are being used as EVENT NAMES: backtick-quoted,
# and shaped like one. A guidance file that names a move the stored graph does
# not declare is the exact defect the revision edges were added to repair -- it
# told authors to request something the engine would refuse -- so the check is
# worth running against the engine's own copy rather than the Rust table.
EVENT_SHAPED = re.compile(r"`((?:revise|phase)-[a-z-]+|[a-z-]+-ready|approved|changes-requested)`")


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["graph"]


def guidance_text(state):
    declaration = state.get("static_guidance")
    if isinstance(declaration, str):
        return declaration
    if isinstance(declaration, dict):
        return declaration.get("text", "") or ""
    return ""


def edges(graph):
    transitions = graph["transitions"]
    print("transitions", len(transitions))
    print("gateless", sum(1 for t in transitions if not t["gate_ids"]))
    for transition in sorted(
        transitions, key=lambda t: (t["source_state_id"], t["event_id"])
    ):
        print(
            "edge",
            transition["source_state_id"],
            transition["event_id"],
            transition["target_state_id"],
            ",".join(transition["gate_ids"]) or "-",
        )


def vocabulary(graph):
    # Guidance legitimately names GATES as well as events -- a refusal reads
    # "phase-review failed", and an author has to be able to look that up. Both
    # vocabularies are declared in the same projection, so both count as
    # declared; what must not appear is a token that is neither.
    events = {t["event_id"] for t in graph["transitions"]}
    gates = {gate for t in graph["transitions"] for gate in t["gate_ids"]}
    declared = events | gates
    total = 0
    for state in graph["states"]:
        named = set(EVENT_SHAPED.findall(guidance_text(state)))
        total += len(named)
        for token in sorted(named - declared):
            print("UNDECLARED", state["id"], token)
    print(
        "vocabulary checked", total, "mention(s) against",
        len(events), "event(s) and", len(gates), "gate(s)",
    )


def main():
    mode, path = sys.argv[1], sys.argv[2]
    graph = load(path)
    {"edges": edges, "vocabulary": vocabulary}[mode](graph)


if __name__ == "__main__":
    main()
