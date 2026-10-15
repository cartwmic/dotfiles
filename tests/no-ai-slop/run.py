#!/usr/bin/env python3
"""Behavioural tests for the no-ai-slop skill.

usage: run.py SKILL_DIR OUT_DIR [N=5] [MODEL=anthropic/claude-opus-5-5] [CASE ...]

Builds a tool-less prompt with the skill's four files inline, runs each case N
times through pi -p, applies fixed regex checks, and writes results.json plus a
summary table. Checks are probabilistic: compare pass rates before and after a
skill change, same model, same N.
"""
import json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

FILES = ["SKILL.md", "eval.md", "voice-profile.md", "voice-excerpts.md"]

T1 = ("Here's the thing: the cache layer exists to cut read latency for the dashboard.\n\n"
      "The retry policy is about protecting downstream services, not about hiding errors. "
      "It runs three attempts with 200 ms backoff.")
T2 = ("It's worth noting that the deletion flow spans ServiceA and ServiceB. "
      "ServiceB handles the deletion queue via a cronjob.")
T3 = ("Per RFC 9110 §15.5.5, the service returns 404 for unknown IDs. "
      "Signal classification: each response is labelled grounded or ungrounded.")
T4 = ("Codex is a powerful tool. It truly streamlines planning. "
      "Many developers find it transformative for their workflow.")
T5 = T1 + "\n\nThe job runs nightly at 02:00 UTC."
T6 = "Our new caching layer is a pivotal, transformative improvement for the platform."
T7 = ("In today's world, observability is pivotal. It's not about dashboards, it's about answers. "
      "Every team needs alerts.")

def split(out):
    m = re.search(r"(?im)^\W*(what changed)\b", out)
    return (out[:m.start()], out[m.start():]) if m else (out, "")

def labels(out):
    got = []
    for l in out.splitlines():
        m = re.match(r"\s*[-*]\s*\*\*(.+?)\*\*", l)
        if m:
            got.append(re.sub(r"[\s:.\u2014-]+$", "", m.group(1)).strip().lower())
    return got

CONTRAST = re.compile(r"(?i),\s*not\b|rather than|instead of|in place of|but only|yet only|less about|\bunlike\b|\bnot\s+(?:just|only|merely)\b|\bnot\b[^.\n]{0,80}\bbut\b|\b(?:it|this|that)(?:'s| is| isn't)\s+not\b[^.\n]*\.\s*(?:it|this|that)(?:'s| is)\b")  # standalone negation after a claim is allowed by SKILL.md

def c(name, fn): return (name, fn)

CASES = {
 "T1e-contrast-scan": dict(mode="Edit", req="Edit mode: remove AI-slop patterns from the TEXT.", text=T1, checks=[
   c("no contrast in output", lambda o,e,r: not CONTRAST.search(e)),
   c("protected facts kept", lambda o,e,r: "three attempts" in e and "200 ms" in e),
   c("report quotes the retry hit on a contrast line", lambda o,e,r: any(re.search("contrast",l,re.I) and re.search("not about",l,re.I) for l in r.splitlines())),
 ]),
 "T1d-detect-contrast": dict(mode="Detect", req="Detect mode: audit the TEXT. Do not rewrite.", text=T1, checks=[
   c("retry sentence flagged as binary contrast", lambda o,e,r: any(re.search("binary contrast",l,re.I) and re.search("not about",l,re.I) for l in o.splitlines())),
 ]),
 "T2-voice-line": dict(mode="Edit", req="Edit mode: repair this generated draft of my explainer.", text=T2, checks=[
   c("Voice line names profile loaded + systems explainer", lambda o,e,r: bool(re.search(r"(?im)^\W*voice:\s*profile loaded;\s*register:\s*systems explainer", o))),
   c("names kept", lambda o,e,r: "ServiceA" in e and "ServiceB" in e),
 ]),
 "T3-citation-colon": dict(mode="Edit", req="Edit mode: tighten my design doc.", text=T3, checks=[
   c("citation kept", lambda o,e,r: "RFC 9110 §15.5.5" in e or "No material edit needed" in o),
   c("label colon kept", lambda o,e,r: "Signal classification:" in e or "No material edit needed" in o),
 ]),
 "T4-no-excerpt-contrast": dict(mode="Edit", req="Edit mode: rewrite this generated draft in my opinion voice.", text=T4, checks=[
   c("no contrast in output", lambda o,e,r: not CONTRAST.search(e)),
   c("no invented source or number", lambda o,e,r: not re.search(r"(?i)according to|studies|survey|\d", e)),
 ]),
 "T5-report-statuses": dict(mode="Edit", req="Edit mode: remove AI-slop patterns from the TEXT.", text=T5, checks=[
   c("portability line with paragraph count", lambda o,e,r: bool(re.search(r"(?i)portab\w*[^\n]*\b3\b[^\n]*paragraph|\b3\b[^\n]*paragraphs?[^\n]*(examined|checked)", r))),
   c("at least 10 status tokens", lambda o,e,r: len(re.findall(r"(?i)\b(pass|fail|not run)\b", r)) >= 10),
 ]),
 "T6-no-invented-fact": dict(mode="Edit", req="Edit mode: remove AI-slop patterns from the TEXT.", text=T6, checks=[
   c("no added metric or mechanism", lambda o,e,r: not re.search(r"(?i)latenc|faster|speed|reduc|\d|%|throughput|scal|performance|hit rate|load", e)),
   c("puffery removed", lambda o,e,r: not re.search(r"(?i)pivotal|transformative", e)),
 ]),
 "T7-detect-labels": dict(mode="Detect", req="Detect mode: audit the TEXT. Do not rewrite.", text=T7, checks=[
   c("ordered canonical labels", lambda o,e,r: labels(o) == ["throat clearing","importance puffery","binary contrast templates","maxims and counterfactuals"]),
 ]),
}

def prompt(skill_dir, case):
    parts = ["You are an agent that has been given the skill files below. Treat them as already read. "
             "You have no tools. Follow the skill exactly and answer in its output shape.\n"]
    for f in FILES:
        parts.append("=== " + f + "\n" + open(os.path.join(skill_dir, f)).read())
    parts.append("=== TASK\n" + case["req"] + "\n\n=== TEXT\n" + case["text"])
    return "\n\n".join(parts)

def run_one(args):
    name, i, skill_dir, out_dir, model = args
    case = CASES[name]
    p = os.path.join(out_dir, f"{name}.{i}.out")
    if not os.path.exists(p):
        res = subprocess.run(["pi","-p","--no-session","--no-tools","-ns","-ne","--model",model],
                             input=prompt(skill_dir, case), capture_output=True, text=True, timeout=600)
        open(p,"w").write(res.stdout)
    o = open(p).read()
    e, r = split(o)
    results = {}
    for cn, fn in case["checks"]:
        try: results[cn] = bool(fn(o,e,r))
        except Exception: results[cn] = False
    return name, i, results

def main():
    skill_dir, out_dir = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    model = sys.argv[4] if len(sys.argv) > 4 else "anthropic/claude-opus-5-5"
    only = sys.argv[5:] or list(CASES)
    os.makedirs(out_dir, exist_ok=True)
    jobs = [(nm, i, skill_dir, out_dir, model) for nm in only for i in range(n)]
    with ThreadPoolExecutor(8) as ex:
        done = list(ex.map(run_one, jobs))
    agg = {}
    for nm, i, res in done:
        for cn, ok in res.items():
            agg.setdefault(nm, {}).setdefault(cn, []).append(ok)
    # T7 also needs cross-run consistency
    if "T7-detect-labels" in only:
        sets = set()
        for i in range(n):
            sets.add(tuple(labels(open(os.path.join(out_dir, f"T7-detect-labels.{i}.out")).read())))
        agg["T7-detect-labels"]["identical across runs"] = [len(sets) == 1] * n
    json.dump(agg, open(os.path.join(out_dir, "results.json"), "w"), indent=1)
    total = passed = 0
    for nm, cs in agg.items():
        for cn, oks in cs.items():
            print(f"{sum(oks)}/{len(oks)}  {nm}: {cn}")
            total += len(oks); passed += sum(oks)
    print(f"TOTAL {passed}/{total}")

if __name__ == "__main__":
    main()
