#!/usr/bin/env python3
"""Parse raw intent calibration evidence and derive release qualification."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

AXES = ["solution-agnostic","outside-verifiable","scope-fenced","constraints-are-limits","problem-grounded"]
IDENTITY = re.compile(r"\[rule=([^ ]+) condition=([^\]]+)\]")


def load(path):
    with open(path) as fh: return json.load(fh)


def identity_present(reason, expected):
    return (expected["rule"],expected["condition"]) in IDENTITY.findall(reason or "")

def identity_leads(reason, expected):
    match=IDENTITY.match(reason or "")
    return bool(match and match.groups()==(expected["rule"],expected["condition"]))


def classify(args):
    manifest=load(args.manifest); case=next(c for c in manifest["cases"] if c["id"]==args.case)
    errors=[]; category="match"; raw={}
    try: reply=load(args.response)
    except Exception as error:
        reply={}; errors.append(f"malformed provider response: {error}"); category="harness_error"
    result=reply.get("result",{}) if isinstance(reply,dict) else {}
    if args.provider_exit != 0:
        errors.append(f"provider exited {args.provider_exit}"); category="harness_error"
    kind=result.get("kind")
    diagnostics=result.get("diagnostics") or []
    if kind=="evaluation_error":
        messages=[str(d.get("message","")) for d in diagnostics]
        if any(d.get("code")=="judge.indeterminate" or "no determinate verdict" in d.get("message","") for d in diagnostics):
            category="indeterminate"
        else: category="harness_error"
        errors.extend(messages or ["provider returned evaluation_error"])
    elif kind!="verdicts" and category=="match":
        category="harness_error"; errors.append(f"provider result kind is {kind!r}, expected verdicts")

    verdict_records=[v for v in result.get("verdicts",[]) if isinstance(v,dict)]
    verdict_groups={gate:[v for v in verdict_records if v.get("gate_id")==gate] for gate in ("intent-ready","intent-semantic")}
    verdicts={gate:rows[0].get("passed") for gate,rows in verdict_groups.items() if len(rows)==1}
    evidence=result.get("evidence",[]) if isinstance(result,dict) else []
    axis_records={}; consensus_records=[]; rubrics_records=[]
    for item in evidence:
        metadata=item.get("metadata") or {}
        if item.get("kind")=="intent-judgment" and metadata.get("axis"):
            axis_records.setdefault(metadata["axis"],[]).append(metadata)
        elif item.get("kind")=="intent-judgment-consensus": consensus_records.append(metadata)
        elif item.get("kind")=="judge-rubrics" and metadata.get("gate_id")=="intent-semantic": rubrics_records.append(metadata)
    axes={axis:rows[0] for axis,rows in axis_records.items() if len(rows)==1}
    consensus=consensus_records[0] if len(consensus_records)==1 else None
    rubrics_record=rubrics_records[0] if len(rubrics_records)==1 else None
    expected_roster=[case["selected_axis"]] if args.mode=="targeted" else AXES
    expected_final=case.get("expected_full_final",case["expected_final"]) if args.mode=="all_axes" else case["expected_final"]
    expected_final_axis=case.get("expected_full_final_axis",case["expected_final_axis"]) if args.mode=="all_axes" else case["expected_final_axis"]
    if category=="match":
        for gate,rows in verdict_groups.items():
            if len(rows)!=1: errors.append(f"expected exactly one {gate} verdict, found {len(rows)}")
        for axis,rows in axis_records.items():
            if len(rows)!=1: errors.append(f"expected exactly one {axis} evidence record, found {len(rows)}")
        if len(consensus_records)!=1: errors.append(f"expected exactly one consensus evidence record, found {len(consensus_records)}")
        if len(rubrics_records)!=1: errors.append(f"expected exactly one intent rubric evidence record, found {len(rubrics_records)}")
        if set(axes)!=set(expected_roster): errors.append(f"axis roster {sorted(axes)} != {sorted(expected_roster)}")
        selected=axes.get(case["selected_axis"])
        if not selected: errors.append("selected axis evidence missing")
        else:
            if selected.get("passed") != (case["expected_axis"]["verdict"]=="pass"): errors.append("selected axis verdict mismatch")
            if not identity_leads(selected.get("reason"),case["expected_axis"]): errors.append("selected axis reason does not begin with expected controlling identity")
            if selected.get("replayed"): errors.append("axis evidence replayed from cache")
            if selected.get("model") != args.axis_model: errors.append(f"axis model {selected.get('model')!r} != {args.axis_model!r}")
        if args.mode=="all_axes":
            for axis in AXES:
                if axis==case["selected_axis"]: continue
                if not axes.get(axis,{}).get("passed"): errors.append(f"non-controlling axis {axis} did not pass")
        expected_pass=expected_final["verdict"]=="pass"
        if verdicts.get("intent-semantic") != expected_pass: errors.append("binding intent-semantic verdict mismatch")
        if not consensus: errors.append("consensus evidence missing")
        else:
            if consensus.get("passed") != expected_pass: errors.append("consensus verdict mismatch")
            if not identity_present(consensus.get("reason"),expected_final): errors.append("consensus reason lacks expected policy identity")
            if args.mode=="targeted":
                if not identity_present(consensus.get("reason"),expected_final_axis): errors.append("consensus reason lacks expected selected-axis identity")
            else:
                finding_identities={match.groups() for metadata in axes.values() if (match:=IDENTITY.match(metadata.get("reason") or ""))}
                consensus_identities=set(IDENTITY.findall(consensus.get("reason") or ""))
                expected_identity=(expected_final_axis["rule"],expected_final_axis["condition"])
                if expected_identity not in consensus_identities and not finding_identities.intersection(consensus_identities): errors.append("consensus reason lacks a supplied or corrected selected-axis identity")
            if consensus.get("replayed"): errors.append("consensus evidence replayed from cache")
            if consensus.get("model") != args.consensus_model: errors.append(f"consensus model {consensus.get('model')!r} != {args.consensus_model!r}")
            embedded=consensus.get("axes")
            if not isinstance(embedded,list): errors.append("consensus embedded axis roster missing")
            else:
                embedded_by_axis={row.get("axis"):row for row in embedded if isinstance(row,dict) and row.get("axis")}
                if len(embedded)!=len(embedded_by_axis) or set(embedded_by_axis)!=set(expected_roster): errors.append("consensus embedded axis roster is duplicate, missing, or unexpected")
                for axis,metadata in axes.items():
                    row=embedded_by_axis.get(axis)
                    if not row or set(row)!={"axis","passed","reason"} or row.get("passed")!=metadata.get("passed") or row.get("reason")!=metadata.get("reason"):
                        errors.append(f"consensus embedded {axis} finding differs from outer axis evidence")
        for axis,metadata in axes.items():
            if metadata.get("rubrics") != args.rubric_set: errors.append(f"axis {axis} rubric identity mismatch")
        if consensus and consensus.get("rubrics") != args.rubric_set: errors.append("consensus rubric identity mismatch")
        if not rubrics_record: errors.append("judge-rubrics evidence missing")
        else:
            if rubrics_record.get("rubrics") != args.rubric_set: errors.append("judge-rubrics identity mismatch")
            if rubrics_record.get("axis_model") != args.axis_model: errors.append("judge-rubrics axis model mismatch")
            if rubrics_record.get("consensus_model") != args.consensus_model: errors.append("judge-rubrics consensus model mismatch")
    routes=[]
    if args.route_log and Path(args.route_log).exists():
        for line in Path(args.route_log).read_text().splitlines():
            try: routes.append(json.loads(line))
            except json.JSONDecodeError: errors.append("route log contains malformed JSON")
    if case["lane"]=="challenge" and category=="match":
        delegated=[r for r in routes if r.get("route")=="delegated" and r.get("model")==args.consensus_model]
        intercepted=[r for r in routes if r.get("route")=="intercepted" and r.get("model")==args.axis_model]
        if not 1 <= len(delegated) <= 2: errors.append(f"expected one delegated consensus call, plus at most one provider retry; found {len(delegated)}")
        expected_intercepts={case["selected_axis"]} if args.mode=="targeted" else {a for a in AXES if not (a=="constraints-are-limits" and "constraints" not in load(Path(args.manifest).parent/case["fixture"]))}
        got_intercepts={r.get("axis") for r in intercepted}
        if got_intercepts!=expected_intercepts: errors.append(f"intercepted axes {sorted(got_intercepts)} != {sorted(expected_intercepts)}")
        for axis in expected_intercepts:
            count=sum(r.get("axis")==axis for r in intercepted)
            if not 1 <= count <= 2: errors.append(f"expected one controlled {axis} call, plus at most one provider retry; found {count}")
        if any(r.get("route") not in {"delegated","intercepted"} for r in routes): errors.append("route log contains unknown route")
    if errors and category=="match": category="semantic_mismatch"
    raw={"verdicts":verdicts,"axes":axes,"consensus":consensus,"judge_rubrics":rubrics_record,"diagnostics":diagnostics,"routes":routes}
    observation={
        "case":case["id"],"lane":case["lane"],"mode":args.mode,"attempt":args.attempt,
        "sequence":args.sequence,"observed_at":datetime.now(timezone.utc).isoformat(),
        "classification":category,"errors":errors,"expected_axis":case["expected_axis"],
        "expected_final_axis":expected_final_axis,"expected_final":expected_final,"requested_axis_model":args.axis_model,
        "requested_consensus_model":args.consensus_model,"rubric_set":args.rubric_set,
        "provider_exit":args.provider_exit,"response_path":str(Path(args.response).resolve()),
        "stderr_path":str(Path(args.stderr).resolve()),"raw":raw,
    }
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(observation,indent=2)+"\n")
    mark={"match":"ok","semantic_mismatch":"MISS","indeterminate":"????","harness_error":"ERR"}[category]
    detail="" if not errors else f" -- {errors[0]}"
    print(f"  {mark:<4} {case['id']:<42} {args.mode} {args.attempt}{detail}")
    return 0 if category=="match" else 1


def aggregate(args):
    manifest=load(args.manifest); all_ids=[c["id"] for c in manifest["cases"]]
    selected=args.cases or all_ids; partial=set(selected)!=set(all_ids)
    release=args.profile=="release"
    targeted_required=manifest["targeted_attempts"] if release else 1
    all_axes_required=1 if release else 0
    records=[]
    for path in sorted(Path(args.observations).glob("*/*.json")):
        try: records.append(load(path))
        except Exception: pass
    by_case={cid:[] for cid in selected}
    for record in records:
        if record.get("case") in by_case: by_case[record["case"]].append(record)
    summaries=[]; qualified=not partial if release else True
    for case in manifest["cases"]:
        cid=case["id"]
        if cid not in by_case: continue
        rows=sorted(by_case[cid],key=lambda r:r.get("sequence",0))
        targeted=[r for r in rows if r.get("mode")=="targeted"]
        full=[r for r in rows if r.get("mode")=="all_axes"]
        errors=[]
        if len(targeted)!=targeted_required: errors.append(f"requires {targeted_required} targeted observations, found {len(targeted)}")
        if [r.get("attempt") for r in targeted] != list(range(1,targeted_required+1)): errors.append(f"targeted attempts are not consecutive 1..{targeted_required}")
        if len(full)!=all_axes_required: errors.append(f"requires {all_axes_required} all-axis observations, found {len(full)}")
        for row in rows:
            if row.get("classification")!="match": errors.append(f"{row.get('mode')} attempt {row.get('attempt')}: {row.get('classification')}")
        ok=not errors
        summaries.append({"id":cid,"lane":case["lane"],"status":case["status"],"qualified":ok,"errors":errors,"observations":rows,"live_case":case.get("live_case")})
        qualified &= ok
    summary_by_id={c["id"]:c for c in summaries}
    for summary in summaries:
        if release and summary["lane"]=="challenge":
            pair=summary_by_id.get(summary["live_case"])
            if not pair or not pair["qualified"]:
                summary["qualified"]=False; summary["errors"].append("paired live case is absent or nonqualifying"); qualified=False
    missing={case_id for case_id, rows in by_case.items() if not rows}
    if missing: qualified=False
    if release:
        qualification="qualified" if qualified else ("partial" if partial else "nonqualifying")
    else:
        qualification="diagnostic-pass" if qualified else "diagnostic-fail"
    report={
        "schema_version":1,"profile":args.profile,"qualification":qualification,
        "complete_manifest":release and not partial,"generated_at":datetime.now(timezone.utc).isoformat(),
        "live_axis_model":args.axis_model,"challenge_axis_model":"intent-calibration/controlled-axis-v1","consensus_model":args.consensus_model,"rubric_set":args.rubric_set,
        "targeted_attempts_required":targeted_required,"all_axis_attempts_required":all_axes_required,
        "selected_cases":selected,"missing_cases":sorted(missing),"cases":summaries,
    }
    Path(args.output).write_text(json.dumps(report,indent=2)+"\n")
    label="release qualification" if release else "smoke diagnostic"
    print(f"intent {label}: {report['qualification']} ({sum(c['qualified'] for c in summaries)}/{len(selected)} cases)")
    return 0 if qualified else 1


def show(args):
    report=load(args.report)
    print(f"qualification: {report['qualification']}")
    print(f"models: live-axis={report['live_axis_model']} challenge-axis={report['challenge_axis_model']} consensus={report['consensus_model']}")
    print(f"rubric set: {report['rubric_set']}")
    for case in report["cases"]:
        print(f"  {'PASS' if case['qualified'] else 'FAIL'} {case['id']} ({case['lane']})")
        for error in case["errors"]: print(f"       {error}")
        if args.reasons:
            for obs in case["observations"]:
                print(f"       {obs['mode']} {obs['attempt']}: {obs['classification']}")
                for axis,data in obs.get("raw",{}).get("axes",{}).items(): print(f"         {axis}: {data.get('reason','')}")
                consensus=obs.get("raw",{}).get("consensus") or {}
                if consensus: print(f"         consensus: {consensus.get('reason','')}")
    return 0 if report["qualification"] in {"qualified","diagnostic-pass"} else 1


def parser():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="command",required=True)
    o=sub.add_parser("observe");
    for name in ("manifest","case","mode","response","stderr","output","axis-model","consensus-model","rubric-set"): o.add_argument(f"--{name}",required=True)
    o.add_argument("--attempt",type=int,required=True); o.add_argument("--sequence",type=int,required=True); o.add_argument("--provider-exit",type=int,required=True); o.add_argument("--route-log"); o.set_defaults(func=classify)
    a=sub.add_parser("aggregate");
    for name in ("manifest","observations","output","axis-model","consensus-model","rubric-set"): a.add_argument(f"--{name}",required=True)
    a.add_argument("--profile",choices=("release","smoke"),default="release")
    a.add_argument("cases",nargs="*"); a.set_defaults(func=aggregate)
    s=sub.add_parser("show"); s.add_argument("report"); s.add_argument("--reasons",action="store_true"); s.set_defaults(func=show)
    return p

if __name__=="__main__":
    args=parser().parse_args(); raise SystemExit(args.func(args))
