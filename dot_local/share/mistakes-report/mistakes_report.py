#!/usr/bin/env python3
"""mistakes-report: one weekly page on shartifacts with two tables of repeated mistakes. Contract and state files: README.md.

Table A: blocking review findings and escapes (defects that got past review), each given one class by a small model.
Table B: failed tool calls in the Claude Code session files, counted by tool and the first line of the error. No model.
Standard library only. The model call and the page host are arguments, so the tests replace both.
"""
import argparse
import concurrent.futures
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEEK = timedelta(days=7)
CALL_SECONDS = 600    # one model call
BATCH = 20            # findings per model call
WORKERS = 4           # model calls in flight
TITLE = "Repeated mistakes: weekly report"
EXIT_LINE = re.compile(r"^Exit code \d+$")   # a Bash command's own exit status: counted in one line, not as a table row
KEY_CHARS = 100       # failures group by tool and the first 100 characters of the error's first line (a hook's refusal text varies after that)
BAD_ARGS = re.compile(r"Invalid parameters for tool '[^']+'")   # every argument-check failure of one tool is one group, whatever argument it names


def utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- reading ----------

def read_review_log(review_dir):
    """Blocking findings and escapes from <review_dir>/*/findings.jsonl -> list of items, each with a stable cache key."""
    items, seen = [], set()
    for path in sorted(glob.glob(os.path.join(review_dir, "*", "findings.jsonl"))):
        folder = os.path.basename(os.path.dirname(path))
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                kind = r.get("event")
                if kind == "finding" and r.get("effective") == "blocking":
                    key = "%s|%s" % (folder, r["id"])
                    item = {"kind": "finding", "item": folder, "round": r.get("round"), "text": r.get("text") or "",
                            "detail": r.get("obligation") or ""}
                elif kind == "escape":
                    digest = hashlib.sha1(("%s|%s|%s" % (r.get("item"), r.get("head"), r.get("text"))).encode()).hexdigest()[:12]
                    key = "%s|escape|%s" % (folder, digest)
                    item = {"kind": "escape", "item": r.get("item") or folder, "round": r.get("round"), "text": r.get("text") or "",
                            "detail": "found by: " + (r.get("found_by") or "")}
                else:
                    continue
                if key in seen or not r.get("at"):
                    continue
                seen.add(key)
                item.update(key=key, at=utc(r["at"]))
                items.append(item)
    return items


def first_line(content):
    """The error's first line; when the next line is an "at [...]" pointer (which argument), it is added, so "Missing key" says which key."""
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    lines = [" ".join(re.sub(r"</?tool_use_error>", "", l).split()) for l in str(content or "").splitlines()]
    lines = [l for l in lines if l]
    if not lines:
        return "(empty error)"
    if len(lines) > 1 and lines[1].startswith("at ") and not EXIT_LINE.match(lines[0]):
        return lines[0] + " " + lines[1]
    return lines[0]


def group_key(msg):
    m = BAD_ARGS.match(msg)
    return m.group(0) if m else msg[:KEY_CHARS]


def scan_tool_errors(sessions_dir):
    """Failed tool results in <sessions_dir>/**/*.jsonl -> (failures [(time, tool, first line)], stats).
    A result counts once per tool_use_id: the files repeat records per content block and hold copies of resumed sessions."""
    tools, results, files = {}, {}, 0
    for path in glob.glob(os.path.join(sessions_dir, "**", "*.jsonl"), recursive=True):
        files += 1
        with open(path, errors="replace") as fh:
            for line in fh:
                if '"tool_use"' not in line and '"tool_result"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("type") not in ("user", "assistant") or not r.get("timestamp"):
                    continue          # api-request-blob records repeat tool text but are not results
                content = (r.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use" and b.get("id"):
                        tools.setdefault(b["id"], b.get("name") or "?")
                    elif b.get("type") == "tool_result" and b.get("tool_use_id") and b["tool_use_id"] not in results:
                        results[b["tool_use_id"]] = (r["timestamp"], bool(b.get("is_error")), first_line(b.get("content")) if b.get("is_error") else "")
    failures = [(utc(ts), tools.get(i, "?"), msg) for i, (ts, bad, msg) in results.items() if bad]
    return failures, {"files": files, "results": len(results), "failed": len(failures)}


# ---------- classifying (the model sits behind model_fn) ----------

def classes_hash(config):
    return hashlib.sha256(json.dumps([config["model"], config["classes"]], sort_keys=True).encode()).hexdigest()[:16]


def build_prompt(config, batch):
    lines = ["Give each numbered review finding exactly one class from this list.", ""]
    lines += ["- %s: %s. %s" % (c["id"], c["name"], c["description"]) for c in config["classes"]]
    lines += ["", 'Reply with only a JSON object that maps each number to a class id, like {"1": "logic-bug", "2": "other"}.', ""]
    for n, it in enumerate(batch, 1):
        label = "ESCAPE (a defect found after review passed)" if it["kind"] == "escape" else "BLOCKING FINDING"
        body = " ".join(it["text"].split())[:1500]
        detail = " ".join(it["detail"].split())[:300]
        lines.append("%d. %s [%s]: %s%s" % (n, label, it["item"], body, (" | " + detail) if detail else ""))
    return "\n".join(lines)


def parse_reply(text, count, class_ids):
    """-> {1-based number: class id} for each valid entry in the reply."""
    try:
        data = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        return {}
    out = {}
    for k, v in data.items():
        if str(k).isdigit() and 1 <= int(k) <= count and v in class_ids:
            out[int(k)] = v
    return out


def call_claude(prompt, model):
    """The real model call: the claude CLI, headless, with nothing else loaded. -> {text, input_tokens, output_tokens, cost_usd}."""
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--no-session-persistence", "--tools", "",
           "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "user", "--settings", '{"disableAllHooks":true}',
           "--effort", "low", "--system-prompt", "You label review findings. Reply with JSON only."]
    with tempfile.TemporaryDirectory() as cwd:
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=CALL_SECONDS)
        except subprocess.TimeoutExpired:
            raise RuntimeError("claude did not answer within %d seconds" % CALL_SECONDS)
    out = r.stdout[r.stdout.index("{"):] if "{" in r.stdout else ""
    try:
        data = json.loads(out)
    except ValueError:
        raise RuntimeError("claude gave no JSON (exit %s): %s" % (r.returncode, (r.stderr or r.stdout)[:300]))
    if data.get("is_error"):
        raise RuntimeError("claude failed: %s" % str(data.get("result"))[:300])
    u = (data.get("modelUsage") or {}).get(model) or {}
    return {"text": data.get("result") or "",
            "input_tokens": u.get("inputTokens", 0) + u.get("cacheReadInputTokens", 0) + u.get("cacheCreationInputTokens", 0),
            "output_tokens": u.get("outputTokens", 0), "cost_usd": data.get("total_cost_usd") or 0.0}


def classify(items, labels, config, model_fn):
    """Fill labels[key] for every item without one. -> (usage, keys left without a class, error texts). A failed call loses only its own batch.
    Cost is list price as the CLI reports it."""
    todo = [it for it in items if it["key"] not in labels]
    ids = {c["id"] for c in config["classes"]}
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "classified": len(todo)}
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]

    errors = []

    def one(batch):
        got, spent = {}, []
        for _ in range(2):
            missing = [(n, it) for n, it in enumerate(batch, 1) if n not in got]
            if not missing:
                break
            sub = [it for _, it in missing]
            try:
                reply = model_fn(build_prompt(config, sub), config["model"])
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                errors.append(str(e))
                break
            spent.append(reply)
            for n, cid in parse_reply(reply["text"], len(sub), ids).items():
                got[missing[n - 1][0]] = cid
        return batch, got, spent

    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        futures = [pool.submit(one, b) for b in batches]
        for f in futures:
            batch, got, spent = f.result()
            for s in spent:
                usage["calls"] += 1
                usage["input_tokens"] += s["input_tokens"]
                usage["output_tokens"] += s["output_tokens"]
                usage["cost_usd"] += s["cost_usd"]
            for n, cid in got.items():
                labels[batch[n - 1]["key"]] = cid
    return usage, [it["key"] for it in todo if it["key"] not in labels], errors


# ---------- counting (pure) ----------

def windows(now):
    return {"this": (now - WEEK, now + timedelta(seconds=1)), "last": (now - 2 * WEEK, now - WEEK)}


def in_window(t, w):
    return w[0] <= t < w[1]


def class_counts(items, labels, kind, wins):
    out = {}
    for it in items:
        if it["kind"] != kind:
            continue
        row = out.setdefault(labels[it["key"]], {"this": 0, "last": 0, "all": 0})
        row["all"] += 1
        for name, w in wins.items():
            row[name] += in_window(it["at"], w)
    return out


def examples(items, labels, kind, wins, per_class=2):
    out = {}
    for it in sorted(items, key=lambda x: x["at"], reverse=True):
        if it["kind"] != kind or not (kind == "escape" or any(in_window(it["at"], w) for w in wins.values())):
            continue
        quote = " ".join(it["text"].split())
        quote = quote if len(quote) <= 170 else quote[:167].rstrip() + "..."
        lst = out.setdefault(labels[it["key"]], [])
        if len(lst) < per_class:
            lst.append({"item": it["item"], "round": it["round"], "quote": quote})
    return out


def tool_counts(failures, w):
    """-> ({(tool, first line): n}, n Bash-style exit-status results)."""
    rows, exits = Counter(), 0
    for t, tool, msg in failures:
        if in_window(t, w):
            if EXIT_LINE.match(msg):
                exits += 1
            else:
                rows[(tool, group_key(msg))] += 1
    return rows, exits


def tool_rows(this, last, failures, top=10):
    """Top rows by the bigger of the two weeks. Each row shows the commonest full first line that has its key."""
    shown = {}
    for _, tool, msg in failures:
        shown.setdefault((tool, group_key(msg)), Counter())[msg] += 1
    keys = set(this) | set(last)
    ranked = sorted(keys, key=lambda k: (-max(this.get(k, 0), last.get(k, 0)), -this.get(k, 0), k))[:top]
    return [{"tool": k[0], "error": min(shown[k], key=lambda m: (-shown[k][m], m)) if k in shown else k[1],
             "variants": len(shown.get(k, ())), "this": this.get(k, 0), "last": last.get(k, 0)} for k in ranked]


# ---------- the page (pure) ----------

CSS = """
@font-face{font-family:"Inter";src:url("/vendor/fonts/inter.woff2") format("woff2");font-weight:100 900;font-style:normal;font-display:swap}
@font-face{font-family:"Cormorant Garamond";src:url("/vendor/fonts/cormorant-garamond-500.woff2") format("woff2");font-weight:400 600;font-style:normal;font-display:swap}
@font-face{font-family:"JetBrains Mono";src:url("/vendor/fonts/jetbrains-mono.woff2") format("woff2");font-weight:100 800;font-style:normal;font-display:swap}
:root{color-scheme:light dark;--canvas:light-dark(#f9f8f6,#1c1a19);--primary-text:light-dark(#b5523b,#e8917a);
--surface-soft:light-dark(#f2efeb,#232120);--surface-card:light-dark(#ebe6e0,#2b2826);--hairline:light-dark(#e6e0d9,#3c3734);
--ink:light-dark(#1a1716,#f5f1ee);--body:light-dark(#403b38,#cec6c1);--muted:light-dark(#6e6863,#a69e98);
--font-display:"Cormorant Garamond","EB Garamond",Garamond,"Times New Roman",serif;--font-body:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
--font-code:"JetBrains Mono",ui-monospace,SFMono-Regular,Consolas,monospace;font-family:var(--font-body);color:var(--ink);background:var(--canvas)}
*{box-sizing:border-box}
body{margin:0;font:16px/1.55 var(--font-body);color:var(--ink);background:var(--canvas)}
h1,h2{font-family:var(--font-display);font-weight:400;letter-spacing:-.02em}
h1{font-size:clamp(30px,5vw,52px);line-height:1.05;margin:.2em 0}
h2{font-size:clamp(24px,3.5vw,34px);line-height:1.1;margin:0 0 .4em}
p,li{color:var(--body)}
code{font-family:var(--font-code);font-size:13px;background:var(--surface-soft);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
.page{max-width:1100px;margin:auto;padding:48px 16px}
.page>section+section{margin-top:48px}
.eyebrow{color:var(--muted);font-size:12px;font-weight:500;letter-spacing:1.5px;text-transform:uppercase}
.card{background:var(--surface-card);padding:20px 24px;border-radius:12px}
.wrap{overflow-x:auto;margin:12px 0}
table{border-collapse:collapse;width:100%;min-width:560px;font-size:14px}
th,td{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--hairline);color:var(--body)}
th{font-size:12px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);font-weight:500}
td.n{white-space:nowrap;font-variant-numeric:tabular-nums;text-align:right}
td strong{color:var(--ink)}
.small{font-size:13px;color:var(--muted)}
.ex{margin:4px 0 0}
"""


def fmt_range(a, b):
    return "%d %s to %d %s %d" % (a.day, a.strftime("%b"), b.day, b.strftime("%b"), b.year)


def render_page(m):
    h = escape
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           "<title>%s</title><style>%s</style></head><body><main class=\"page\">" % (h(TITLE), CSS)]
    out.append('<section><p class="eyebrow">Weekly report · made %s UTC</p><h1>%s</h1>' % (m["generated"], h(TITLE)))
    out.append("<p><strong>This week:</strong> %s (UTC). <strong>Last week:</strong> %s. %s</p></section>"
               % (fmt_range(*m["this"]), fmt_range(*m["last"]), h(m["last_source"])))
    out.append('<section><div class="card"><h2>How to read this</h2><ul>'
               "<li>Your agents keep making some mistakes more than once. This page counts them so you can fix the biggest one at its root (a check or a test) instead of patching each case.</li>"
               "<li><strong>Tables 1 and 2</strong> use the review log. A <em>blocking finding</em> is a reviewer saying a change must not merge as it is. An <em>escape</em> is a defect found after review passed it. "
               "A small model (%s) gives each one a single kind from a fixed list of %d kinds. Each row shows two examples.</li>"
               "<li><strong>Table 3</strong> counts tool calls that failed, by tool and the first line of the error. No model is used. Rows are ranked by the bigger of the two weeks, so a mistake you fixed stays visible with a count of 0.</li>"
               "<li>After you fix a kind of mistake, its number should fall to near zero the next week. If it does not, the fix did not work.</li>"
               "</ul></div></section>" % (h(m["model"]), len(m["classes"])))
    names = {c["id"]: c for c in m["classes"]}

    def exs(lst):
        return "".join('<p class="ex small"><code>%s</code> round %s: “%s”</p>' % (h(e["item"]), h(str(e["round"])), h(e["quote"])) for e in lst) or "<span class=\"small\">none</span>"

    out.append('<section><h2>1. Blocking review findings, by kind</h2><div class="wrap"><table><tr><th>Kind</th><th>This week</th><th>Last week</th><th>Two examples</th></tr>')
    rows = sorted(m["findings"].items(), key=lambda kv: (-(kv[1]["this"] + kv[1]["last"]), kv[0]))
    for cid, c in rows:
        if c["this"] + c["last"] == 0:
            continue
        out.append('<tr><td><strong>%s</strong></td><td class="n">%d</td><td class="n">%d</td><td>%s</td></tr>'
                   % (h(names[cid]["name"]), c["this"], c["last"], exs(m["examples"]["finding"].get(cid, []))))
    out.append("</table></div><p class=\"small\">%d blocking findings this week, %d last week.</p></section>"
               % (sum(c["this"] for c in m["findings"].values()), sum(c["last"] for c in m["findings"].values())))

    out.append('<section><h2>2. Escapes: defects found after review passed the change</h2><div class="wrap"><table>'
               "<tr><th>Kind</th><th>This week</th><th>Last week</th><th>All records</th><th>Two latest examples</th></tr>")
    total = sum(c["all"] for c in m["escapes"].values())
    for cid, c in sorted(m["escapes"].items(), key=lambda kv: (-kv[1]["all"], kv[0])):
        out.append('<tr><td><strong>%s</strong></td><td class="n">%d</td><td class="n">%d</td><td class="n">%d of %d</td><td>%s</td></tr>'
                   % (h(names[cid]["name"]), c["this"], c["last"], c["all"], total, exs(m["examples"]["escape"].get(cid, []))))
    out.append('</table></div><p class="small">“All records” counts every escape in the review log, not only these two weeks.</p></section>')

    out.append('<section><h2>3. Tool calls that fail the same way</h2><div class="wrap"><table>'
               "<tr><th>Tool</th><th>First line of the error</th><th>This week</th><th>Last week</th></tr>")
    for r in m["tools"]:
        err = r["error"] if len(r["error"]) <= 240 else r["error"][:237] + "..."
        more = '<span class="small"> (and %d other wording%s of the same error)</span>' % (r["variants"] - 1, "" if r["variants"] == 2 else "s") if r["variants"] > 1 else ""
        out.append('<tr><td><code>%s</code></td><td>%s%s</td><td class="n">%d</td><td class="n">%d</td></tr>' % (h(r["tool"]), h(err), more, r["this"], r["last"]))
    out.append("</table></div><p class=\"small\">Not in the table: %d Bash results this week (%d last week) that only say “Exit code N”. That is a command's own exit status (a failing test, a grep with no match), not a mistake in calling the tool.</p>"
               % (m["exits"]["this"], m["exits"]["last"]))
    if m["partial_logs"]:
        out.append('<p class="small">Session files on this host before about %s are partial, so last week\'s counts in this table are low.</p>' % h(m["partial_logs"]))
    out.append("</section>")

    u = m["usage"]
    out.append('<section><p class="small">Run %s. Model %s: %d new items sorted in %d call%s, %d input tokens and %d output tokens, list-price cost $%.4f; %d items were already in the saved answers. '
               "Tool table read %d session files, %d tool results, %d failed.</p></section></main></body></html>"
               % (h(m["run_id"]), h(m["model"]), u["classified"], u["calls"], "" if u["calls"] == 1 else "s", u["input_tokens"], u["output_tokens"],
                  u["cost_usd"], m["cached"], m["stats"]["files"], m["stats"]["results"], m["stats"]["failed"]))
    return "".join(out)


# ---------- state and publishing (the edges) ----------

def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    Path(tmp).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def find_snapshot(state_dir, last_end, hash_):
    """The saved snapshot whose week ends within a day and a half of the start of this week, made with the same class list."""
    best = None
    for p in glob.glob(os.path.join(state_dir, "snapshots", "*.json")):
        s = read_json(p, None)
        if not s or s.get("classes_hash") != hash_:
            continue
        gap = abs((utc(s["end"]) - last_end).total_seconds())
        if gap <= 36 * 3600 and (best is None or gap < best[0]):
            best = (gap, s, os.path.basename(p))
    return best


def http(base, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def publish(base, state_dir, html):
    """Create the page once, then update it in place. -> (page id, version before or None, version after, was_created)."""
    idfile = Path(state_dir) / "page-id"
    aid = idfile.read_text().strip() if idfile.exists() else ""
    if not aid:
        a = http(base, "POST", "/api/artifacts", {"title": TITLE, "kind": "html", "content": html, "tags": ["mistakes-report"],
                                                  "description": "Weekly repeated-mistakes report, updated in place by mistakes-report"})
        idfile.parent.mkdir(parents=True, exist_ok=True)
        idfile.write_text(a["id"] + "\n")
        return a["id"], None, 1, True
    for _ in range(3):           # a version can land between the GET and the PUT (409)
        base_version = max(r["version"] for r in http(base, "GET", "/api/artifacts/" + aid)["revisions"])
        try:
            http(base, "PUT", "/api/artifacts/" + aid, {"content": html, "base_version": base_version})
            return aid, base_version, base_version + 1, False
        except urllib.error.HTTPError as e:
            e.close()
            if e.code != 409:
                raise
    raise RuntimeError("page update failed: 409 three times")


# ---------- one run ----------

def run(a, model_fn=None, now=None):
    started = time.monotonic()
    model_fn = model_fn or call_claude
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    config = read_json(a.classes, None)
    if not config:
        raise RuntimeError("cannot read the class list: %s" % a.classes)
    chash = classes_hash(config)
    wins = windows(now)

    items = [it for it in read_review_log(a.review_dir) if it["kind"] == "escape" or it["at"] >= wins["last"][0]]
    cache_path = os.path.join(a.state_dir, "classifications.json")
    cache = read_json(cache_path, {})
    labels = cache.get("labels", {}) if cache.get("classes_hash") == chash else {}
    cached = sum(1 for it in items if it["key"] in labels)
    usage, failed, errors = classify(items, labels, config, model_fn)
    write_json(cache_path, {"classes_hash": chash, "labels": labels})     # answers already paid for are kept even if some failed
    if failed:
        raise RuntimeError("%d items got no class%s; nothing published; run again (saved answers are kept)"
                           % (len(failed), (" (" + errors[0] + ")") if errors else " after two tries"))

    failures, stats = scan_tool_errors(a.sessions_dir)
    this_rows, this_exits = tool_counts(failures, wins["this"])
    snap = None if a.no_snapshot_lookup else find_snapshot(a.state_dir, wins["last"][1], chash)
    if snap:
        last_rows = {(t, e): n for t, e, n in snap[1]["tool_errors"]}
        last_exits, last_source = snap[1]["command_exits"], "Last week comes from the snapshot saved on %s." % snap[1]["end"][:10]
        last_findings, last_escapes = snap[1]["findings"], snap[1]["escapes"]
    else:
        last_rows, last_exits = tool_counts(failures, wins["last"])
        last_source = "No saved snapshot for last week, so last week was counted from the logs on this run."
        last_findings = {c: v["last"] for c, v in class_counts(items, labels, "finding", {"last": wins["last"]}).items()}
        last_escapes = {c: v["last"] for c, v in class_counts(items, labels, "escape", {"last": wins["last"]}).items()}

    findings = class_counts(items, labels, "finding", {"this": wins["this"]})
    escapes = class_counts(items, labels, "escape", {"this": wins["this"]})
    for table, last in ((findings, last_findings), (escapes, last_escapes)):
        for cid in set(last) - set(table):
            table[cid] = {"this": 0, "last": 0, "all": 0}
        for cid, row in table.items():
            row["last"] = last.get(cid, 0)
    partial = config.get("logs_partial_before") if wins["last"][0] < datetime.fromisoformat(config["logs_partial_before"]).replace(tzinfo=timezone.utc) else ""
    model = {"generated": now.strftime("%Y-%m-%d %H:%M"), "run_id": uuid.uuid4().hex[:12], "this": wins["this"][0:1] + (now,), "last": wins["last"],
             "last_source": last_source, "model": config["model"], "classes": config["classes"], "findings": findings, "escapes": escapes,
             "examples": {"finding": examples(items, labels, "finding", {"t": wins["this"], "l": wins["last"]}),
                          "escape": examples(items, labels, "escape", {})},
             "tools": tool_rows(this_rows, last_rows, failures), "exits": {"this": this_exits, "last": last_exits}, "partial_logs": partial,
             "usage": usage, "cached": cached, "stats": stats}
    html = render_page(model)
    Path(a.state_dir).mkdir(parents=True, exist_ok=True)
    Path(a.state_dir, "page.html").write_text(html)
    result = {"run_id": model["run_id"], "page_html": str(Path(a.state_dir, "page.html")), "model": model}
    if not a.no_publish:
        aid, before, after, created = publish(a.shartifacts, a.state_dir, html)
        result.update(page_id=aid, url="%s/view/%s" % (a.shartifacts, aid), version_before=before, version_after=after, created=created)
    snapshot = {"start": stamp(wins["this"][0]), "end": stamp(now), "classes_hash": chash, "findings": {c: v["this"] for c, v in findings.items()},
                "escapes": {c: v["this"] for c, v in escapes.items()}, "tool_errors": [[t, e, n] for (t, e), n in sorted(this_rows.items())],
                "command_exits": this_exits}
    if not a.no_publish:                       # a preview must not replace the snapshot of a published run
        write_json(os.path.join(a.state_dir, "snapshots", now.strftime("%Y-%m-%d") + ".json"), snapshot)
    record = {"run_id": model["run_id"], "at": stamp(now), "duration_s": round(time.monotonic() - started, 1), "published": not a.no_publish,
              "page_id": result.get("page_id"), "version": result.get("version_after"), "classified": usage["classified"], "calls": usage["calls"],
              "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "cost_usd": round(usage["cost_usd"], 6),
              "blocking_this_week": sum(v["this"] for v in findings.values()), "escapes_all": sum(v["all"] for v in escapes.values()),
              "tool_results": stats["results"], "tool_failed": stats["failed"], "last_week_from": "snapshot" if snap else "logs"}
    with open(os.path.join(a.state_dir, "runs.jsonl"), "a") as fh:
        fh.write(json.dumps(record) + "\n")
    result["record"] = record
    return result


def parser():
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    traces = os.environ.get("AGENT_TRACES_DIR") or os.path.expanduser("~/.local/share/agent-traces")
    p = argparse.ArgumentParser(description="Publish the weekly repeated-mistakes page (README.md).")
    p.add_argument("--review-dir", default=os.path.join(traces, "emitted", "review"))
    p.add_argument("--sessions-dir", default=os.path.expanduser("~/.claude/projects"))
    p.add_argument("--state-dir", default=os.path.join(state, "mistakes-report"))
    p.add_argument("--classes", default=str(HERE / "classes.json"))
    p.add_argument("--shartifacts", default=os.environ.get("SHARTIFACTS_URL") or "https://shartifacts.internal.cartwmic.com")
    p.add_argument("--no-publish", action="store_true", help="write page.html in the state directory and stop")
    p.add_argument("--no-snapshot-lookup", action="store_true", help="count last week from the logs even when a snapshot exists")
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        r = run(a)
    except (RuntimeError, urllib.error.URLError, OSError) as e:
        print("mistakes-report: %s" % e, file=sys.stderr)
        return 1
    rec = r["record"]
    print("classified %d new items in %d calls: %d input tokens, %d output tokens, list-price cost $%.4f"
          % (rec["classified"], rec["calls"], rec["input_tokens"], rec["output_tokens"], rec["cost_usd"]))
    if r.get("url"):
        print("%s page %s version %s -> %s" % ("created" if r["created"] else "updated", r["page_id"], r["version_before"], r["version_after"]))
        print(r["url"])
    else:
        print("page written to " + r["page_html"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
