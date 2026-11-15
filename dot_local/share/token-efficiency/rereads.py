#!/usr/bin/env python3
"""Split cache-read tokens by WHAT is being re-read, and flag re-reading that
looks avoidable. Needs usage.sqlite from collect.py.

Usage: rereads.py [--since ISO] [--until ISO] [--json OUT]

Method. For each session the script rebuilds what was in the prompt at every
request: the fixed start-up text, then each prompt, tool result, attachment and
model reply as it arrived, dropped again at each compaction. Each request's
real cache-read token count is then shared out over the pieces in the prompt at
that moment, in proportion to their size. So bucket totals add up to the real
cache-read total; the split inside a request is by size and is an estimate.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from analyze import seat_of, fmt, table  # noqa: E402
from collect import bash_head, STATE_DIR  # noqa: E402

ROOT = os.path.expanduser('~/.claude/projects')
CPT = 3.0  # chars per token for sizing text pieces against model output tokens

B_SYS = 'Claude Code system prompt'
B_SEAT = 'Playbook and seat text'
B_ART = 'Tool definitions: Artifact (unused)'
B_TOOLS = 'Tool definitions: all others'
B_SKILLS = 'Skills list'
B_INSTR = 'Instructions file (CLAUDE.md)'
B_MEM = 'Memory: index and recall results'
B_LISTS = 'Tool-name, agent-type and MCP server lists'
B_HARN = 'Harness reminders'
B_BRIEF = 'The brief'
B_WAKE = 'Wake and event payloads, messages from agents'
B_SUB = 'Subagent results'
B_HUMAN = "Michael's own messages"
B_FILE = 'File contents the agent read'
B_SEARCH = 'Search and listing output'
B_CMD = 'Other command output'
B_T3 = 'Thread and task reads'
B_WEB = 'Web pages and search results'
B_OTHERTOOL = 'Other tool results'
B_SUMMARY = 'Compaction summaries'
B_TEXT = "History: the model's replies"
B_THINK = "History: the model's thinking"
B_CALLS = "History: shell commands and scripts the model ran"
B_WRITES = "History: file writes and edits the model made"
B_SENT = "History: briefs and messages the model sent"
PERSIST = {B_SYS, B_ART, B_TOOLS, B_INSTR}
DEDUPE = {B_SYS, B_SEAT, B_ART, B_TOOLS, B_INSTR, B_SKILLS, B_LISTS}
PATH_RE = re.compile(r'(?:[\w.~-]*/)+[\w.@-]+|\b[\w-]+\.(?:md|py|ts|tsx|js|json|toml|yaml|yml|rs|ex|exs|sh|html|css|txt|sql|jsonl)\b')


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get('type') == 'text':
                out.append(b.get('text') or '')
    return '\n'.join(out)


def result_text(content):
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get('type') == 'text':
                    out.append(b.get('text') or '')
                elif b.get('type') == 'image':
                    out.append('x' * 4500)
                else:
                    out.append(json.dumps(b))
    return '\n'.join(out)


def prompt_bucket(origin, p, idx):
    if origin == 'human':
        return B_HUMAN
    if p.startswith('Delegated task ') or p.startswith('<task-notification') or origin == 'task_notification':
        return B_SUB
    if idx == 0:
        return B_BRIEF
    return B_WAKE


def tool_bucket(name, cmd):
    if name == 'Read':
        return B_FILE
    if name in ('Grep', 'Glob'):
        return B_SEARCH
    if name == 'Bash':
        h = bash_head(cmd or '').split()[0] if cmd else '?'
        if h in ('cat', 'sed', 'head', 'tail', 'wc', 'nl', 'less', 'awk'):
            return B_FILE
        if h in ('grep', 'rg', 'find', 'ls', 'fd', 'which', 'tree'):
            return B_SEARCH
        return B_CMD
    if name == 'Agent':
        return B_SUB
    if name.startswith('mcp__hindsight'):
        return B_MEM
    if name.startswith('mcp__t3-code'):
        return B_T3
    if name in ('WebFetch', 'WebSearch') or name.startswith('mcp__context7') or name.startswith('mcp__playwright') or name.startswith('mcp__browser'):
        return B_WEB
    return B_OTHERTOOL


def scan(job):
    path, owned, is_sub = job
    # owned: msgid -> (cr, in_window)
    items = []   # dict(b, w, born, flags..)
    reqs = []    # per request index: scale (cr / total weight), filled later
    req_cr = []
    order = {}
    live_w = 0.0
    seg_start_item = 0
    seg_ends = []       # (request idx at compaction, item idx at compaction)
    tool_meta = {}      # tool_use_id -> (name, cmd, path)
    seen_hash = set()
    seen_path = set()
    live_att = set()
    later_text = []     # (req idx, text) of model tool inputs and replies, for "named again"
    turn_items = []     # (item idx of prompt, first req idx)
    have_shape = False
    first_assistant = False
    pending_out = {}    # msgid -> (think, text_chars, call_chars, out)
    out_tokens = {}
    snapshots = 0

    def add(bucket, chars, **kw):
        if chars <= 0:
            return None
        if bucket in DEDUPE:
            key = (bucket, int(chars))
            if key in live_att:
                return None
            live_att.add(key)
        it = dict(b=bucket, w=chars / CPT, born=len(reqs), **kw)
        items.append(it)
        return it

    def add_fixed(system_chars, tools):
        if system_chars > 40000:
            add(B_SYS, 12000)
            add(B_SEAT, system_chars - 12000, keep=True)
        else:
            add(B_SYS, system_chars)
        art = sum(n for k, n in tools.items() if k == 'Artifact')
        add(B_ART, art)
        add(B_TOOLS, sum(tools.values()) - art)

    try:
        fh = open(path, errors='replace')
    except OSError:
        return None
    for line in fh:
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get('type')
        if t == 'api-request-shape' and not have_shape:
            sh = d.get('shape') or {}
            sysc = sum(len(x.get('text') or '') for x in (sh.get('system') or []) if isinstance(x, dict))
            tools = {(x.get('name') or '?'): len(json.dumps(x)) for x in (sh.get('tools') or []) if isinstance(x, dict)}
            add_fixed(sysc, tools)
            have_shape = True
        elif t == 'attachment':
            a = d.get('attachment') or {}
            at = a.get('type')
            if at == 'instructions':
                for f in a.get('files') or []:
                    n = len(json.dumps(f))
                    add(B_MEM if 'MEMORY.md' in str(f.get('path')) else B_INSTR, n)
            elif at == 'skill_listing':
                add(B_SKILLS, len(a.get('content') or ''))
            elif at == 'invoked_skills':
                add(B_SKILLS, len(json.dumps(a.get('skills') or '')))
            elif at == 'hook_additional_context':
                c = a.get('content')
                add(B_SEAT, len(c if isinstance(c, str) else json.dumps(c or '')))
            elif at in ('deferred_tools_delta', 'agent_listing_delta'):
                add(B_LISTS, len(json.dumps(a.get('addedLines') or '')))
            elif at == 'mcp_instructions_delta':
                add(B_LISTS, len(json.dumps(a.get('addedBlocks') or '')))
            elif at == 'file':
                c = a.get('content')
                add(B_FILE, len(c if isinstance(c, str) else json.dumps(c or '')), kind='attached')
            elif at == 'queued_command':
                p = a.get('prompt')
                p = p if isinstance(p, str) else text_of(p)
                add(prompt_bucket(a.get('origin'), p or '', 1), len(p or ''), payload=True)
            elif at in ('environment', 'model', 'date', 'session_context', 'remote_session_change', 'auto_mode',
                        'silent_turn_reminder', 'task_status', 'edited_text_file', 'compact_file_reference'):
                add(B_HARN, len(json.dumps({k: v for k, v in a.items() if k != 'type'})))
        elif t == 'assistant':
            m = d.get('message') or {}
            mid = m.get('id')
            if not mid or m.get('model') == '<synthetic>':
                continue
            first_assistant = True
            u = m.get('usage') or {}
            tx = cc = cw_ = cs_ = 0
            for b in m.get('content') or []:
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'text':
                    tx += len(b.get('text') or '')
                    later_text.append((len(reqs), b.get('text') or ''))
                elif b.get('type') == 'tool_use':
                    inp = b.get('input') or {}
                    js = json.dumps(inp)
                    name = b.get('name') or '?'
                    if name in ('Write', 'Edit', 'NotebookEdit'):
                        cw_ += len(js)
                    elif name in ('Agent', 'SendMessage') or name.startswith('mcp__t3-code'):
                        cs_ += len(js)
                    else:
                        cc += len(js)
                    later_text.append((len(reqs), js))
                    cmd = inp.get('command') if name == 'Bash' else None
                    fp = inp.get('file_path') if name == 'Read' else None
                    if name == 'Bash' and cmd:
                        ps = PATH_RE.findall(cmd.split('&&')[-1])
                        fp = ps[-1] if ps else None
                    tool_meta[b.get('id')] = (name, cmd, fp)
            if mid not in order:
                order[mid] = len(reqs)
                cr, inw = owned.get(mid, (0, False))
                reqs.append(None)
                req_cr.append(cr if inw else 0)
                pending_out[mid] = [0, 0, 0, 0, len(reqs), 0, 0]
                if turn_items and turn_items[-1][1] is None:
                    turn_items[-1][1] = len(reqs) - 1
                if turn_items:
                    turn_items[-1][2] += 1
            po = pending_out[mid]
            po[0] = (u.get('output_tokens_details') or {}).get('thinking_tokens') or 0
            po[1] = max(po[1], 0) + tx
            po[2] += cc
            po[5] += cw_
            po[6] += cs_
            po[3] = u.get('output_tokens') or 0
            out_tokens[mid] = po[3]
            if turn_items:
                turn_items[-1][3] = max(turn_items[-1][3], 0)
        elif t == 'user':
            m = d.get('message') or {}
            content = m.get('content')
            if d.get('isCompactSummary'):
                # compaction: everything but the fixed start-up text leaves the prompt
                flush_out(pending_out, items)
                seg_ends.append((len(reqs), len(items)))
                seen_hash.clear()
                seen_path.clear()
                for key in [k for k in live_att if k[0] not in PERSIST]:
                    live_att.discard(key)
                add(B_SUMMARY, len(text_of(content)))
                continue
            is_tr = False
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get('type') == 'tool_result':
                        is_tr = True
                        name, cmd, fp = tool_meta.get(b.get('tool_use_id'), ('?', None, None))
                        txt = result_text(b.get('content'))
                        bk = tool_bucket(name, cmd)
                        h = hashlib.md5(txt.encode('utf-8', 'replace')).hexdigest() if len(txt) > 400 else None
                        dup = bool(h and h in seen_hash)
                        if h:
                            seen_hash.add(h)
                        reread = False
                        if bk == B_FILE and fp:
                            base = os.path.basename(fp)
                            reread = base in seen_path
                            seen_path.add(base)
                        add(bk, len(txt), tool=name, dup=dup, reread=reread, path=fp, big=max(0, len(txt) - 6000) / CPT)
            if not is_tr and not d.get('isMeta'):
                txt = text_of(content)
                if txt.strip():
                    idx = 0 if not turn_items else 1
                    bk = prompt_bucket(d.get('turnOrigin') or ('sub' if is_sub else ''), txt.strip(), idx)
                    it = add(bk, len(txt), payload=True)
                    turn_items.append([it, None, 0, 0])
    fh.close()
    flush_out(pending_out, items)
    if not have_shape and not items:
        return None
    # turns answered with one short reply: mark payload as "only acknowledged"
    outs = {}
    for mid, i in order.items():
        outs[i] = out_tokens.get(mid, 0)
    for it, first, n, _ in turn_items:
        if it is not None and first is not None and n == 1 and outs.get(first, 0) < 250 and it['b'] in (B_WAKE, B_SUB):
            it['ack_only'] = True
    # file read "named again": does the base name show up in any later model reply or tool call?
    lt_idx = [i for i, _ in later_text]
    for it in items:
        if it['b'] == B_FILE and it.get('path'):
            base = os.path.basename(it['path'])
            it['named_later'] = any(i >= it['born'] and base in s for i, s in later_text) if len(base) > 3 else True
    # replay: share each request's cache read over live items by size
    n = len(reqs)
    bounds = [b for b in seg_ends] + [(n, len(items))]
    res = defaultdict(float)
    flags = defaultdict(float)
    seg_req0 = 0
    seg_item0 = 0
    fixed = [it for it in items if it['b'] in PERSIST or it.get('keep')]
    for req_end, item_end in bounds:
        seg_items = fixed + [it for it in items[seg_item0:item_end] if it['b'] not in PERSIST and not it.get('keep')]
        seg_items.sort(key=lambda it: it['born'])
        # running weight and prefix sums of scale
        S = [0.0] * (req_end - seg_req0 + 1)
        k = 0
        live = 0.0
        for r in range(seg_req0, req_end):
            while k < len(seg_items) and seg_items[k]['born'] <= r:
                live += seg_items[k]['w']
                k += 1
            s = (req_cr[r] / live) if live > 0 else 0.0
            S[r - seg_req0 + 1] = S[r - seg_req0] + s
        tot = S[-1]
        if tot > 0:
            for it in seg_items:
                b0 = max(it['born'], seg_req0) - seg_req0
                if b0 > len(S) - 1:
                    continue
                share = it['w'] * (tot - S[b0])
                if share <= 0:
                    continue
                res[it['b']] += share

                def later(age):
                    j = min(len(S) - 1, b0 + age)
                    return it['w'] * (tot - S[j])
                flags['old25|' + it['b']] += later(25)
                flags['old100|' + it['b']] += later(100)
                if it.get('dup'):
                    flags['dup|' + it['b']] += share
                if it.get('reread') and not it.get('dup'):
                    flags['reread|' + it['b']] += share
                if it.get('big'):
                    flags['over2k|' + it['b']] += share * it['big'] / it['w']
                if it.get('ack_only'):
                    flags['ack|' + it['b']] += share
                if it['b'] == B_FILE and it.get('named_later') is False:
                    flags['unnamed|' + it['b']] += later(5)
                if it.get('tool', '').startswith('mcp__t3-code'):
                    flags['t3big|' + it['b']] += share * it.get('big', 0) / it['w']
        seg_req0, seg_item0 = req_end, item_end
    cnt = defaultdict(float)
    for it in items:
        cnt['n|' + it['b']] += 1
        cnt['w|' + it['b']] += it['w']
    return dict(path=path, res=dict(res), flags=dict(flags), cnt=dict(cnt), cr=sum(req_cr))


def flush_out(pending_out, items):
    for mid, (think, tx, cc, out, born, cw_, cs_) in list(pending_out.items()):
        if out <= 0:
            continue
        rest = max(0, out - think)
        tot = (tx + cc + cw_ + cs_) or 1
        for b, w in ((B_THINK, think), (B_TEXT, rest * tx / tot), (B_CALLS, rest * cc / tot), (B_WRITES, rest * cw_ / tot), (B_SENT, rest * cs_ / tot)):
            if w > 0:
                items.append(dict(b=b, w=float(w), born=born))
    pending_out.clear()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='2026-11-11T18:00:00Z')
    ap.add_argument('--until', default='2026-11-13T01:14:00Z')
    ap.add_argument('--db', default=os.path.join(STATE_DIR, 'usage.sqlite'))
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    db = sqlite3.connect(a.db)
    db.row_factory = sqlite3.Row
    files = {r['path']: dict(r) for r in db.execute('select * from files')}
    by_session = {(f['project'], f['session']): p for p, f in files.items() if not f['is_sub']}
    for p, f in files.items():
        f['seat'] = seat_of(f)
    for p, f in files.items():
        if f['is_sub'] and f['seat'] == 'unattributed':
            root = by_session.get((f['project'], f['parent']))
            f['seat'] = 'helper of ' + (files[root]['seat'] if root else '?')
    owned = defaultdict(dict)
    total_cr = 0
    for r in db.execute('select path, msgid, cr, ts from requests'):
        inw = a.since <= r['ts'] < a.until
        owned[r['path']][r['msgid']] = (r['cr'], inw)
        if inw:
            total_cr += r['cr']
    jobs = [(os.path.join(ROOT, p), o, files[p]['is_sub']) for p, o in owned.items() if any(v[1] for v in o.values())]
    agg = defaultdict(lambda: defaultdict(float))
    flags = defaultdict(float)
    cnt = defaultdict(float)
    got = 0
    with Pool(max(2, (os.cpu_count() or 4) - 1)) as pool:
        for r in pool.imap_unordered(scan, jobs, chunksize=4):
            if not r:
                continue
            seat = files[os.path.relpath(r['path'], ROOT)]['seat']
            if seat.startswith('helper') or seat in ('unattributed', 'michael-direct'):
                seat = 'other'
            for b, v in r['res'].items():
                agg[b][seat] += v
                agg[b]['all'] += v
                got += v
            for k, v in r['flags'].items():
                flags[k] += v
            for k, v in r['cnt'].items():
                cnt[k] += v
    days = 1.30
    print('# What is being re-read\nwindow %s to %s; cache read in window %s; attributed %s (%.1f%%)' % (
        a.since, a.until, fmt(total_cr), fmt(got), 100 * got / total_cr))
    seats = ['lead', 'builder', 'reviewer', 'coordinator', 'planner', 'other']
    st = {s: sum(agg[b][s] for b in agg) or 1 for s in seats}
    rows = []
    for b, v in sorted(agg.items(), key=lambda kv: -kv[1]['all']):
        rows.append([b, fmt(v['all'] / days), '%.1f%%' % (100 * v['all'] / got)] + ['%.0f%%' % (100 * v[s] / st[s]) for s in seats])
    table('Cache-read tokens by what is being re-read (per day; seat columns are the share of that seat\'s own cache read)',
          ['bucket', 'tokens a day', 'share'] + seats, rows)
    rows = []
    for b, v in sorted(agg.items(), key=lambda kv: -kv[1]['all']):
        t = v['all']
        rows.append([b, fmt(t / days), '%.0f%%' % (100 * flags['old25|' + b] / t), '%.0f%%' % (100 * flags['old100|' + b] / t)])
    table('How old the re-read text is (share of the bucket re-read more than 25 and more than 100 requests after it arrived)',
          ['bucket', 'tokens a day', 'older than 25 requests', 'older than 100 requests'], rows)
    names = {'dup': 'Tool output identical to one already in the prompt',
             'reread': 'A file read again that was already read in this stretch',
             'over2k': 'The part of any tool result beyond its first 2K tokens',
             'ack': 'Wake payloads and reports the agent only acknowledged (one short reply)',
             'unnamed': 'File contents never named again by the agent, from 5 requests after the read',
             't3big': 'Thread and task reads: the part beyond 2K tokens'}
    rows = []
    for k, label in names.items():
        tot = sum(v for kk, v in flags.items() if kk.startswith(k + '|'))
        parts = sorted(((kk.split('|')[1], v) for kk, v in flags.items() if kk.startswith(k + '|')), key=lambda x: -x[1])[:3]
        rows.append([label, fmt(tot / days), '%.1f%%' % (100 * tot / got), '; '.join('%s %s' % (p, fmt(v / days)) for p, v in parts)])
    table('Re-reading that looks avoidable (per day; rows overlap)', ['what', 'tokens a day', 'share of all cache read', 'mostly in'], rows)
    rows = [[b, int(cnt['n|' + b]), fmt(cnt['w|' + b]), fmt(cnt['w|' + b] / max(1, cnt['n|' + b]))] for b in sorted(agg, key=lambda b: -agg[b]['all'])]
    table('Pieces by bucket (whole files of sessions active in the window)', ['bucket', 'pieces', 'tokens added once', 'average size'], rows)
    if a.json:
        json.dump(dict(total_cr=total_cr, attributed=got, buckets={b: dict(v) for b, v in agg.items()}, flags=dict(flags), counts=dict(cnt)),
                  open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
