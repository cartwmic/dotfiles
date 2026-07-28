#!/usr/bin/env python3
"""Read one provider reply and report what the design gates said.

  report.py <out.json>                     print gate and axis verdicts
  report.py --reasons <out.json>           also print each judge's reasoning
  report.py --indeterminate <out.json>     exit 0 if any judge was indeterminate
  report.py --check <expectations.tsv> <case> <out.json>
                                           compare against the expectation and
                                           print one matrix line; exit non-zero
                                           on mismatch
"""
import json
import re
import sys
import textwrap

JUDGE = re.compile(r"judge:([a-z-]+):(pass|fail):(.*)", re.S)


def load(path):
    with open(path) as fh:
        return json.load(fh).get("result", {})


def verdicts(result):
    """gate id -> passed, plus axis id -> (passed, reason)."""
    gates = {v["gate_id"]: v["passed"] for v in result.get("verdicts", [])}
    axes = {}
    for e in result.get("evidence", []):
        m = JUDGE.match(e.get("locator", ""))
        if m:
            axes[m.group(1)] = (m.group(2) == "pass", m.group(3))
    return gates, axes


def indeterminate(result):
    return [d.get("message", "") for d in (result.get("diagnostics") or [])
            if "no determinate verdict" in d.get("message", "")]


def show(result, reasons):
    gates, axes = verdicts(result)
    for gate, passed in gates.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {gate}")
    for axis, (passed, reason) in axes.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {axis}")
        if reasons:
            print(textwrap.indent(textwrap.fill(reason, 92), "        "))
    for message in indeterminate(result):
        print(f"  INDETERMINATE  {message[:160]}")


def expectations(path):
    rows = {}
    with open(path) as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            case, expect, axis, status, note = line.rstrip("\n").split("\t", 4)
            rows[case] = (expect, axis, status, note)
    return rows


def check(expect_path, case, out_path):
    expect, axis, status, _note = expectations(expect_path)[case]
    result = load(out_path)
    stalled = indeterminate(result)
    gates, axes = verdicts(result)

    if stalled:
        print(f"  ????  {case:<26} INDETERMINATE after retry -- {stalled[0][:70]}")
        return 1

    binding = gates.get("design-semantic")
    if binding is None:
        print(f"  ????  {case:<26} no design-semantic verdict in reply")
        return 1

    got = "pass" if binding else "fail"
    ok = got == expect

    detail = ""
    if expect == "fail" and axis not in ("-", "n/a"):
        carried = axes.get(axis)
        if carried is None:
            detail = f"  [axis {axis} did not report]"
            ok = False
        elif carried[0]:
            failing = sorted(a for a, (p, _) in axes.items() if not p)
            carried_by = ", ".join(failing) if failing else "no axis (decider alone)"
            detail = f"  [expected {axis} to fail; failure carried by {carried_by}]"
            ok = False

    mark = "ok  " if ok else "MISS"
    tag = "" if status == "enforced" else f"  ({status})"
    print(f"  {mark}  {case:<26} expected {expect}, got {got}{tag}{detail}")
    return 0 if ok else 1


def main(argv):
    if argv[:1] == ["--check"]:
        return check(argv[1], argv[2], argv[3])
    if argv[:1] == ["--indeterminate"]:
        return 0 if indeterminate(load(argv[1])) else 1
    reasons = argv[:1] == ["--reasons"]
    if reasons:
        argv = argv[1:]
    show(load(argv[0]), reasons)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
