"""workstreams: list-price spend per coordinator workstream, from usage.sqlite (collect.py), the T3 database and the ledger.

No model call. Pure data and text here; the command line is `session-cost workstreams` (session_cost.py).

How a request gets its workstream (every step is a lookup, nothing is guessed):
  1. The request's transcript file belongs to a Claude session. A helper file (Agent-tool subagent) belongs to its parent's session.
  2. T3 records which T3 thread owns that Claude session (provider threads: nativeThreadRef.nativeId -> appThreadId).
  3. From that thread go up the T3 lineage (parentThreadId) to the nearest thread that is a ledger workstream's pane or conversation.
     The nearest one wins, so a builder a lead launched counts for the lead's workstream, not for the coordinator at the top of the tree.
  4. A thread that more than one ledger workstream names is shown under all their names ("A / B"), never under one of them.
A request with no T3 thread, or a thread with no workstream above it, is shown in its own "unmapped" rows, never dropped.

Costs are analyze.py's: list price per token kind, not subscription billing.
"""
import json
import os
import sqlite3
import sys
from collections import defaultdict

import analyze

# the walk up the thread tree and the read-only open are shared with workstream-rank (one way to do it)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'workstream-rank'))
from t3_lineage import nearest, parent_from_payload, readonly  # noqa: E402

NO_THREAD = '(unmapped) no T3 thread'
NO_WORKSTREAM = '(unmapped) T3 thread, no ledger workstream'
UNMAPPED = (NO_THREAD, NO_WORKSTREAM)


def load_t3(path):
    """(parent, title, session_thread): thread -> parent thread, thread -> title, Claude session id -> thread."""
    db = readonly(path)
    parent, title, session_thread = {}, {}, {}
    for thread_id, name, payload in db.execute('select thread_id, title, payload_json from orchestration_v2_projection_threads'):
        parent[thread_id] = parent_from_payload(payload)
        title[thread_id] = name
    for (payload,) in db.execute('select payload_json from orchestration_v2_projection_provider_threads'):
        d = json.loads(payload)
        native = (d.get('nativeThreadRef') or {}).get('nativeId')
        if native and d.get('appThreadId'):
            session_thread[native] = d['appThreadId']
    db.close()
    return parent, title, session_thread


def load_ledger(path):
    """thread id -> sorted names of the ledger workstreams whose pane or conversation is that thread (`t3:<thread id>`)."""
    db = readonly(path)
    names = defaultdict(set)
    for name, pane, conversation in db.execute('select name, pane, conversation from workstreams'):
        for ref in (pane, conversation):
            if ref and ref.startswith('t3:'):
                names[ref[3:]].add(name)
    db.close()
    return {thread: sorted(n) for thread, n in names.items()}


def workstream_of(thread, parent, ledger):
    """Label of the nearest ledger workstream at or above the thread, or None."""
    names = nearest(thread, parent, ledger)
    return ' / '.join(names) if names else None


def root_of(thread, parent):
    seen = set()
    while parent.get(thread) and thread not in seen:
        seen.add(thread)
        thread = parent[thread]
    return thread


def attribute(files, t3, ledger):
    """transcript path -> (group, detail). detail only names what is inside an unmapped group."""
    parent, title, session_thread = t3
    out = {}
    for path, f in files.items():
        session = f['parent'] if f['is_sub'] else f['session']
        thread = session_thread.get(session)
        if thread is None:
            out[path] = (NO_THREAD, f['project'])
            continue
        label = workstream_of(thread, parent, ledger)
        if label is not None:
            out[path] = (label, None)
        else:
            out[path] = (NO_WORKSTREAM, title.get(root_of(thread, parent)) or root_of(thread, parent))
    return out


def blank():
    return dict(requests=0, inp=0, out=0, cr=0, cw=0, usd=0.0)


def add(row, r):
    row['requests'] += 1
    row['inp'] += r['inp']
    row['out'] += r['out']
    row['cr'] += r['cr']
    row['cw'] += r['cw1h'] + r['cw5m']
    row['usd'] += r['usd']


def build(db_path, t3, ledger, since, until):
    """Per group: total row, per-model rows, and (for the unmapped groups) per-detail rows. Uses analyze.py's cost code."""
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    files = analyze.load_files(db)
    reqs = analyze.load_requests(db, files, since, until)
    db.close()
    where = attribute(files, t3, ledger)
    groups = defaultdict(lambda: dict(total=blank(), models=defaultdict(blank), details=defaultdict(blank)))
    for r in reqs:
        group, detail = where[r['path']]
        g = groups[group]
        add(g['total'], r)
        add(g['models'][r['model']], r)
        if detail is not None:
            add(g['details'][detail], r)
    total = blank()
    for g in groups.values():
        for k in total:
            total[k] += g['total'][k]
    first = min((r['ts'] for r in reqs), default=None)
    last = max((r['ts'] for r in reqs), default=None)
    used = {r['path'] for r in reqs}
    sessions = {(files[p]['project'], files[p]['parent'] if files[p]['is_sub'] else files[p]['session']) for p in used}
    return dict(since=since, until=until, first_request=first, last_request=last, total=total, groups=groups, sessions=len(sessions))


def share(usd, total):
    return '%.1f%%' % (100 * usd / total) if total else '-'


def money(v):
    return '$%.2f' % v


def render(rep, db_path, mtime):
    total = rep['total']['usd']
    head = ['workstream / model', 'requests', 'input', 'output', 'cache read', 'cache write', 'list $', 'share']
    rows = []

    def line(label, row):
        return [label, '{:,}'.format(row['requests']), analyze.fmt(row['inp']), analyze.fmt(row['out']), analyze.fmt(row['cr']),
                analyze.fmt(row['cw']), money(row['usd']), share(row['usd'], total)]

    ordered = sorted(rep['groups'].items(), key=lambda kv: (kv[0] in UNMAPPED, -kv[1]['total']['usd'], kv[0]))
    for name, g in ordered:
        rows.append(line(name, g['total']))
        for model, row in sorted(g['models'].items(), key=lambda kv: -kv[1]['usd']):
            rows.append(line('    ' + model, row))
        if name in UNMAPPED:
            for detail, row in sorted(g['details'].items(), key=lambda kv: -kv[1]['usd']):
                rows.append(line('    in: ' + str(detail)[:60], row))
    rows.append(line('TOTAL', rep['total']))
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]

    def fmt_row(r):
        return '  '.join(str(c).ljust(widths[i]) if i == 0 else str(c).rjust(widths[i]) for i, c in enumerate(r))

    mapped = sum(g['total']['usd'] for n, g in rep['groups'].items() if n not in UNMAPPED)
    out = ['workstreams: list-price spend per coordinator workstream, from the Claude Code logs on this host.',
           'Window: %s to %s (requests from %s to %s).' % (rep['since'], rep['until'], rep['first_request'], rep['last_request']),
           'List price = tokens at the public per-token rates in analyze.py (RATES). It is NOT subscription billing.',
           'Attribution: Claude session -> T3 thread (T3 database) -> nearest ancestor thread that is a ledger workstream pane or conversation.',
           'A thread named by several workstreams shows as "A / B". Helper (subagent) requests count with their session.',
           'Not counted: Pi and Codex sessions, advisor-tool calls, threads on other hosts (they show as unmapped).',
           'Usage data: %s, collected %s. Mapped %s of %s (%s); unmapped %s.'
           % (db_path, mtime, money(mapped), money(total), share(mapped, total), share(total - mapped, total)),
           '']
    out += [fmt_row(head), '-' * (sum(widths) + 2 * (len(widths) - 1))] + [fmt_row(r) for r in rows]
    return '\n'.join(out)


def unmapped_share(rep):
    total = rep['total']['usd']
    return sum(g['total']['usd'] for n, g in rep['groups'].items() if n in UNMAPPED) / total if total else 0.0
