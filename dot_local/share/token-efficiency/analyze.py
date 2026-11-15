#!/usr/bin/env python3
"""Tables from usage.sqlite (built by collect.py; default ~/.local/state/token-efficiency).

Usage: analyze.py [--since ISO_UTC] [--until ISO_UTC] [--json OUT.json]

Default window: from COMPLETE_FROM (the fleet moved from the Mac that morning;
earlier days are only partly present on this machine).

Token kinds stay apart. "List $" prices each kind at the list rates below; on
a subscription it is a weight for comparing kinds, not a bill.
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from collect import STATE_DIR  # noqa: E402
# Claude Code logs on this host are complete from here: the fleet moved to this Linux machine that morning.
# Earlier days are only partly present (README, Coverage).
COMPLETE_FROM = '2026-11-11T18:00:00Z'
# $ per million tokens: input, output, cache read, cache write 5m, cache write 1h.
# From dated Anthropic sources (see ../research/01-anthropic-claude-code.md). The Nov 9 audit
# used $0.20 for Sonnet cache reads, so its Sonnet figures run higher than these.
RATES = {
    'claude-opus-5-5': (4, 20, 0.20, 5, 8),
    'claude-sonnet-5-5': (2, 10, 0.10, 2.5, 4),  # cache read cut to $0.10 on 2026-10-07
    'claude-fable-5-2': (8, 40, 0.20, 10, 16),  # $8/$40 per Anthropic's 2026-11-09 release note; cache rates assumed pro rata
    'haiku-short': (0.10, 0.50, 0.01, 0.125, 0.20),
    'haiku-long': (0.50, 2.50, 0.05, 0.625, 1.0),
}


def rate(model, ctx):
    if model.startswith('claude-haiku'):
        return RATES['haiku-long' if ctx > 100_000 else 'haiku-short']
    return RATES.get(model, RATES['claude-sonnet-5-5'])


def seat_of(f):
    """Seat from the brief's Seat line, then from known brief openings."""
    fp = (f['first_prompt'] or '')
    low = fp.lower()
    s = (f['seat_line'] or '').lower()
    if not s:
        m = re.search(r'seat:\s*\**\s*([a-z][a-z /-]{1,30})', low)
        if m:
            s = m.group(1)
        else:
            m = re.search(r'\b(reviewer|builder|planner|lead) seat\b', low)
            if m:
                s = m.group(1)
    if 'coordinator thread' in low[:120] or "michael's live coordinator" in low[:160] or 'brought up as michael' in low[:120]:
        return 'coordinator'
    if s:
        if any(k in s for k in ('review', 'label', 'judge', 'comparer', 'blind', 'intent check', 'scorer', 'challeng')):
            return 'reviewer'
        if s.startswith('lead') and 'run' not in s:
            return 'lead'
        if any(k in s for k in ('build', 'driver', 'implement', 'worker', 'fetch', 'search', 'helper', 'reader', 'gate', 'browser', 'explor')):
            if 'research' in s:
                return 'planner'
            return 'builder'
        if any(k in s for k in ('plan', 'research', 'investig', 'design', 'analyst', 'synth')):
            return 'planner'
    if 'act as the implementation sub-agent' in low[:80]:
        return 'builder'
    if 'act as the review sub-agent' in low[:80]:
        return 'reviewer'
    if 'act as the research sub-agent' in low[:80] or 'act as the design sub-agent' in low[:80]:
        return 'planner'
    if f['human_turns']:
        return 'michael-direct'
    return 'unattributed'


def turn_kind(origin, prefix, idx):
    p = prefix or ''
    if origin == 'human':
        return 'michael typed'
    if origin == 'task_notification' or p.startswith('<task-notification'):
        return 'background task finished'
    if p.startswith('[coord') or p.startswith('[ask ') or p.startswith('[clock') or p.startswith('[wake'):
        return 'coordinator event'
    if p.startswith('Delegated task '):
        return 'child finished notice'
    if p.startswith('Update on pull request'):
        return 'PR watch'
    if re.match(r'(From (the )?(lead|coordinator|thread|mcp)|mcp:|thread:|Coordinator \()', p):
        return 'message from another agent'
    if idx == 0:
        return 'brief (first turn)'
    return 'other follow-up'


def fmt(n):
    n = float(n or 0)
    for unit, d in (('B', 1e9), ('M', 1e6), ('K', 1e3)):
        if abs(n) >= d:
            return '%.2f%s' % (n / d, unit)
    return '%d' % n


def table(title, header, rows):
    print('\n## ' + title)
    print('| ' + ' | '.join(header) + ' |')
    print('|' + '|'.join('---' for _ in header) + '|')
    for r in rows:
        print('| ' + ' | '.join(str(x) for x in r) + ' |')


def parse_ts(ts):
    return datetime.fromisoformat(ts.replace('Z', '+00:00'))


def request_cost(r):
    """List-price dollars of one request, split by token kind."""
    ctx = r['inp'] + r['cw1h'] + r['cw5m'] + r['cr']
    ri, ro, rr, r5, r1 = rate(r['model'], ctx)
    return dict(inp=r['inp'] * ri / 1e6, out=r['out'] * ro / 1e6, cr=r['cr'] * rr / 1e6,
                cw=(r['cw5m'] * r5 + r['cw1h'] * r1) / 1e6)


def load_files(db):
    """Every transcript file with its seat (own sessions; Agent-tool helpers get 'helper of <root seat>')."""
    files = {r['path']: dict(r) for r in db.execute('select * from files')}
    by_session = {}
    for p, f in files.items():
        if not f['is_sub']:
            by_session[(f['project'], f['session'])] = p
    for p, f in files.items():
        f['seat'] = seat_of(f)
    for p, f in files.items():
        f['root'] = by_session.get((f['project'], f['parent'])) if f['is_sub'] else None
        f['root_seat'] = files[f['root']]['seat'] if f['root'] else None
        if f['is_sub'] and f['seat'] == 'unattributed':
            f['seat'] = 'helper of ' + (f['root_seat'] or '?')
    return files


def load_requests(db, files, since, until):
    """Requests with since <= ts < until, each with ctx, cost split `c`, `usd`, seat, is_sub and PST day."""
    reqs = [dict(r) for r in db.execute('select * from requests where ts>=? and ts<? order by path, seq', (since, until))]
    for r in reqs:
        r['ctx'] = r['inp'] + r['cw1h'] + r['cw5m'] + r['cr']
        c = request_cost(r)
        r['c'] = c
        r['usd'] = sum(c.values())
        r['seat'] = files[r['path']]['seat']
        r['is_sub'] = files[r['path']]['is_sub']
        r['day'] = (parse_ts(r['ts']) - timedelta(hours=8)).strftime('%Y-%m-%d')   # PST
    return reqs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default=COMPLETE_FROM)
    ap.add_argument('--until', default='9999')
    ap.add_argument('--db', default=os.path.join(STATE_DIR, 'usage.sqlite'))
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    db = sqlite3.connect(a.db)
    db.row_factory = sqlite3.Row
    files = load_files(db)
    reqs = load_requests(db, files, a.since, a.until)
    allreqs_first = {}
    for r in db.execute('select path, min(seq) s from requests group by path'):
        allreqs_first[r['path']] = r['s']
    first_ctx = {}
    for r in db.execute('select r.path, r.inp+r.cw1h+r.cw5m+r.cr ctx, r.cw1h+r.cw5m cw, r.cr from requests r join (select path, min(seq) s from requests group by path) m on m.path=r.path and m.s=r.seq'):
        first_ctx[r['path']] = (r['ctx'], r['cw'], r['cr'])
    min_ctx = {}
    for r in db.execute('select f.session s, min(r.inp+r.cw1h+r.cw5m+r.cr) c from requests r join files f using(path) where f.is_sub=0 group by 1'):
        min_ctx[r['s']] = r['c']
    for r in db.execute('select r.path p, min(r.inp+r.cw1h+r.cw5m+r.cr) c from requests r join files f using(path) where f.is_sub=1 group by 1'):
        min_ctx[r['p']] = r['c']
    out = {'window': {'since': a.since, 'until': a.until}}
    if not reqs:
        print('no requests in window')
        return
    t0, t1 = min(r['ts'] for r in reqs), max(r['ts'] for r in reqs)
    hours = (parse_ts(t1) - parse_ts(t0)).total_seconds() / 3600
    days = hours / 24
    out['window'].update(first=t0, last=t1, hours=round(hours, 1))
    print('# Token baseline\nwindow %s to %s (%.1f hours, %.2f days), %d API requests, %d transcript files' % (
        t0, t1, hours, days, len(reqs), len({r['path'] for r in reqs})))

    def agg(keyf, rows=reqs):
        d = defaultdict(lambda: defaultdict(float))
        for r in rows:
            k = keyf(r)
            x = d[k]
            x['n'] += 1
            for f in ('inp', 'cw1h', 'cw5m', 'cr', 'out', 'think', 'usd', 'ctx'):
                x[f] += r[f]
            for f in ('cr', 'cw', 'out'):
                x['usd_' + f] += r['c'][f]
        return d

    def rows_of(d, total_usd):
        rows = []
        for k, x in sorted(d.items(), key=lambda kv: -kv[1]['usd']):
            rows.append([k, int(x['n']), fmt(x['inp']), fmt(x['cw1h'] + x['cw5m']), fmt(x['cr']), fmt(x['out']),
                         fmt(x['ctx'] / x['n']), '$%.0f' % x['usd'], '%.0f%%' % (100 * x['usd'] / total_usd),
                         '%.0f%%' % (100 * x['usd_cr'] / x['usd'] if x['usd'] else 0),
                         '%.0f%%' % (100 * x['usd_cw'] / x['usd'] if x['usd'] else 0),
                         '%.0f%%' % (100 * x['usd_out'] / x['usd'] if x['usd'] else 0)])
        return rows

    H = ['', 'requests', 'fresh input', 'cache write', 'cache read', 'output', 'avg prompt', 'list $', 'share', '$ read', '$ write', '$ output']
    tot = agg(lambda r: 'all')['all']
    T = tot['usd']
    out['totals'] = {k: tot[k] for k in tot}
    out['per_day_rate'] = {k: tot[k] / days for k in ('inp', 'cw1h', 'cw5m', 'cr', 'out', 'usd', 'n')}
    table('Total', H, rows_of(agg(lambda r: 'all'), T))
    print('\nper day: requests %s, cache read %s, cache write %s, output %s, list $%.0f' % (
        fmt(tot['n'] / days), fmt(tot['cr'] / days), fmt((tot['cw1h'] + tot['cw5m']) / days), fmt(tot['out'] / days), T / days))
    table('By seat (own sessions; helpers started with the Agent tool are listed under their own seat line)', H, rows_of(agg(lambda r: r['seat']), T))
    out['by_seat'] = {k: dict(v) for k, v in agg(lambda r: r['seat']).items()}
    table('By model', H, rows_of(agg(lambda r: r['model']), T))
    out['by_model'] = {k: dict(v) for k, v in agg(lambda r: r['model']).items()}
    table('By seat and model', H, rows_of(agg(lambda r: r['seat'] + ' / ' + r['model'].replace('claude-', '') + ' ' + str(r['effort'])), T)[:22])
    table('By day (PST)', H, sorted(rows_of(agg(lambda r: r['day']), T)))
    out['by_day'] = {k: dict(v) for k, v in agg(lambda r: r['day']).items()}
    table('Main thread vs Agent-tool helpers', H, rows_of(agg(lambda r: 'Agent-tool helper' if r['is_sub'] else 'main session'), T))

    # --- context size buckets
    def bucket(c):
        for lim, name in ((50e3, '0-50K'), (100e3, '50-100K'), (150e3, '100-150K'), (200e3, '150-200K'), (300e3, '200-300K'), (467e3, '300-467K')):
            if c < lim:
                return name
        return '467K+'
    order = ['0-50K', '50-100K', '100-150K', '150-200K', '200-300K', '300-467K', '467K+']
    d = agg(lambda r: bucket(r['ctx']))
    table('By prompt size of the request', H, [x for o in order for x in rows_of({o: d[o]}, T) if o in d])
    out['by_ctx_bucket'] = {k: dict(v) for k, v in d.items()}
    seats = sorted({r['seat'] for r in reqs})
    rows = []
    for s in seats:
        rs = [r for r in reqs if r['seat'] == s]
        cr = sum(r['cr'] for r in rs) or 1
        rows.append([s, len(rs), fmt(sum(r['ctx'] for r in rs) / len(rs)),
                     '%.0f%%' % (100 * sum(r['cr'] for r in rs if r['ctx'] > 150e3) / cr),
                     '%.0f%%' % (100 * sum(r['cr'] for r in rs if r['ctx'] > 300e3) / cr),
                     fmt(max(r['ctx'] for r in rs))])
    table('Prompt size by seat', ['seat', 'requests', 'avg prompt', 'cache read in prompts >150K', '>300K', 'max prompt'], rows)

    # --- fixed prefix carry
    # prefix = prompt size of the session's first request (system prompt, tool schemas,
    # instructions, memory index, hooks, and the brief). It is re-read on every later request.
    carry = defaultdict(float)
    sess = defaultdict(list)
    for r in reqs:
        sess[r['path']].append(r)
    pref_tokens = defaultdict(list)
    for p, rs in sess.items():
        P = min_ctx.get(p if files[p]['is_sub'] else files[p]['session'])
        if not P:
            continue
        pref_tokens[files[p]['seat']].append(P)
        for r in rs:
            carry[files[p]['seat']] += min(P, r['cr'])
    tc = sum(carry.values())
    rows = []
    for s in sorted(carry, key=lambda k: -carry[k]):
        srt = sorted(pref_tokens[s])
        rows.append([s, len(srt), fmt(srt[len(srt) // 2]), fmt(carry[s]),
                     '%.0f%%' % (100 * carry[s] / (sum(r['cr'] for r in reqs if r['seat'] == s) or 1))])
    rows.append(['all', sum(len(v) for v in pref_tokens.values()), '', fmt(tc), '%.0f%%' % (100 * tc / tot['cr'])])
    table('Fixed start-up prefix (smallest prompt the session ever sent) re-read on every request', ['seat', 'sessions', 'median smallest prompt', 'prefix tokens re-read', 'share of the seat cache read'], rows)
    out['prefix_carry'] = {'total': tc, 'share_of_cache_read': tc / tot['cr'], 'by_seat': dict(carry),
                           'median_first_prompt': {s: sorted(v)[len(v) // 2] for s, v in pref_tokens.items()}}
    # first request: how much was written vs read from another session's cache
    fw = fr = 0
    nfirst = 0
    for p, rs in sess.items():
        if rs[0]['seq'] == allreqs_first.get(p):
            nfirst += 1
            fw += rs[0]['cw1h'] + rs[0]['cw5m']
            fr += rs[0]['cr']
    print('\nfirst requests of %d sessions started in window: cache written %s, read from an earlier session %s (%.0f%% shared)' % (
        nfirst, fmt(fw), fmt(fr), 100 * fr / max(1, fw + fr)))
    out['first_requests'] = dict(n=nfirst, written=fw, read=fr)
    fs = defaultdict(lambda: defaultdict(float))
    for p, rs in sess.items():
        if rs[0]['seq'] == allreqs_first.get(p):
            x = fs[files[p]['seat']]
            x['n'] += 1
            x['cw'] += rs[0]['cw1h'] + rs[0]['cw5m']
            x['cr'] += rs[0]['cr']
            x['usd'] += rs[0]['c']['cw']
    table('First request of each new session: prefix written fresh vs read from a cache another session left',
          ['seat', 'new sessions', 'avg written', 'avg read from shared cache', 'list $ of the writes'],
          [[k, int(x['n']), fmt(x['cw'] / x['n']), fmt(x['cr'] / x['n']), '$%.0f' % x['usd']] for k, x in sorted(fs.items(), key=lambda kv: -kv[1]['usd'])]
          + [['all', nfirst, fmt(fw / max(1, nfirst)), fmt(fr / max(1, nfirst)), '$%.0f' % sum(x['usd'] for x in fs.values())]])
    out['first_request_writes'] = {k: dict(v) for k, v in fs.items()}

    # --- request shapes: system prompt and tool schemas
    rows = []
    shp = {}
    for r in db.execute('''select s.hash, s.system_chars, s.tools_chars, s.n_tools, s.per_tool, sum(u.n) n
                           from shapes s join shape_use u using(hash) group by 1 order by n desc limit 400'''):
        shp[r['hash']] = dict(r)
    # weight shapes by use, group by main vs helper
    grp = defaultdict(lambda: defaultdict(float))
    for r in db.execute('select u.path, u.hash, u.n from shape_use u'):
        f = files.get(r['path'])
        s = shp.get(r['hash'])
        if not f or not s:
            continue
        k = ('helper: ' + str(f['agent_type'])) if f['is_sub'] else 'main: ' + f['seat']
        g = grp[k]
        g['n'] += r['n']
        g['sys'] += r['n'] * s['system_chars']
        g['tools'] += r['n'] * s['tools_chars']
        g['ntools'] += r['n'] * s['n_tools']
    for k, g in sorted(grp.items(), key=lambda kv: -kv[1]['n'])[:14]:
        rows.append([k, int(g['n']), fmt(g['sys'] / g['n'] / 4), fmt(g['tools'] / g['n'] / 4), '%.0f' % (g['ntools'] / g['n'])])
    table('System prompt and tool schemas sent with each request (all data; tokens = chars / 4, rough)',
          ['who', 'requests logged', 'system prompt tokens', 'tool schema tokens', 'tools'], rows)
    out['shapes'] = {k: dict(v) for k, v in grp.items()}
    # biggest tools in the most used main shape
    top = max(shp.values(), key=lambda s: s['n'])
    per = sorted(json.loads(top['per_tool']).items(), key=lambda kv: -kv[1])
    table('Largest tool schemas in the most used request shape (%d tools, %s tokens total)' % (top['n_tools'], fmt(top['tools_chars'] / 4)),
          ['tool', 'tokens (chars / 4)'], [[k, fmt(v / 4)] for k, v in per[:16]])
    out['top_shape_tools'] = per[:40]

    # --- turns
    turns = defaultdict(lambda: defaultdict(float))
    treqs = defaultdict(list)
    for r in reqs:
        treqs[(r['path'], r['turn'])].append(r)
    tinfo = {}
    for t in db.execute('select * from turns'):
        tinfo[(t['path'], t['turn'])] = t
    noop = defaultdict(lambda: defaultdict(float))
    for (p, ti), rs in treqs.items():
        t = tinfo.get((p, ti))
        kind = turn_kind(t['origin'], t['prefix'], ti) if t else 'unknown'
        seat = files[p]['seat']
        key = (seat, kind)
        x = turns[key]
        x['turns'] += 1
        x['n'] += len(rs)
        x['usd'] += sum(r['usd'] for r in rs)
        x['cr'] += sum(r['cr'] for r in rs)
        x['out'] += sum(r['out'] for r in rs)
        x['ctx'] += sum(r['ctx'] for r in rs)
        if len(rs) == 1 and rs[0]['out'] < 250 and kind not in ('brief (first turn)',):
            y = noop[key]
            y['turns'] += 1
            y['usd'] += rs[0]['usd']
            y['cr'] += rs[0]['cr']
    rows = []
    for k, x in sorted(turns.items(), key=lambda kv: -kv[1]['usd'])[:24]:
        y = noop.get(k, {})
        rows.append([k[0], k[1], int(x['turns']), int(x['n']), fmt(x['ctx'] / x['n']), fmt(x['cr']), '$%.0f' % x['usd'],
                     '%.0f%%' % (100 * x['usd'] / T), int(y.get('turns', 0)), '$%.0f' % y.get('usd', 0)])
    table('What started each turn', ['seat', 'turn started by', 'turns', 'requests', 'avg prompt', 'cache read', 'list $', 'share', 'one-request short-reply turns', 'their list $'], rows)
    out['turns'] = {'%s|%s' % k: dict(v) for k, v in turns.items()}
    out['noop_turns'] = {'%s|%s' % k: dict(v) for k, v in noop.items()}
    nt = sum(v['turns'] for v in noop.values())
    nu = sum(v['usd'] for v in noop.values())
    ncr = sum(v['cr'] for v in noop.values())
    print('\none-request short-reply turns (reply under 250 output tokens, no tool loop): %d turns, cache read %s, list $%.0f (%.1f%%)' % (nt, fmt(ncr), nu, 100 * nu / T))
    out['noop_total'] = dict(turns=nt, usd=nu, cr=ncr)

    # --- cache rewrites
    rw = defaultdict(lambda: defaultdict(float))
    for p, rs in sess.items():
        prev = None
        for r in rs:
            cw = r['cw1h'] + r['cw5m']
            if prev is not None and r['seq'] != allreqs_first.get(p) and r['ctx'] > 20000 and cw > 0.5 * r['ctx']:
                gap = (parse_ts(r['ts']) - parse_ts(prev['ts'])).total_seconds()
                if r['after_compact']:
                    k = 'after a compaction'
                elif gap > 3600:
                    k = 'idle over 1 hour'
                elif gap > 300 and r['cw5m'] >= r['cw1h']:
                    k = 'idle 5-60 min on the 5-minute cache'
                elif gap > 300:
                    k = 'idle 5-60 min on the 1-hour cache (unexpected)'
                else:
                    k = 'under 5 min idle (prefix changed)'
                x = rw[(files[p]['seat'], k)]
                x['n'] += 1
                x['cw'] += cw
                x['usd'] += r['c']['cw']
            prev = r
    rows = [[k[0], k[1], int(x['n']), fmt(x['cw']), '$%.0f' % x['usd']] for k, x in sorted(rw.items(), key=lambda kv: -kv[1]['usd'])[:18]]
    trw = sum(x['usd'] for x in rw.values())
    rows.append(['all', '', int(sum(x['n'] for x in rw.values())), fmt(sum(x['cw'] for x in rw.values())), '$%.0f (%.1f%%)' % (trw, 100 * trw / T)])
    table('Whole-prompt cache rewrites after the first request (over half the prompt written fresh)', ['seat', 'cause', 'requests', 'tokens rewritten', 'list $'], rows)
    out['rewrites'] = {'%s|%s' % k: dict(v) for k, v in rw.items()}
    d = agg(lambda r: r['seat'] + ' / ttl ' + str(r['cache_ttl']))
    table('Cache lifetime requested, by seat', ['seat / ttl', 'requests', '1h writes', '5m writes'],
          [[k, int(x['n']), fmt(x['cw1h']), fmt(x['cw5m'])] for k, x in sorted(d.items())])

    # --- compactions
    rows = []
    comp = [dict(c) for c in db.execute('select * from compactions where ts>=? and ts<?', (a.since, a.until))]
    cs = defaultdict(list)
    for c in comp:
        cs[(files[c['path']]['seat'], c['trigger'])].append(c)
    for k, v in sorted(cs.items()):
        pre = sorted(c['pre'] for c in v)
        rows.append([k[0], k[1], len(v), fmt(pre[0]), fmt(pre[len(pre) // 2]), fmt(pre[-1]), fmt(sum(c['post'] for c in v) / len(v))])
    table('Compactions', ['seat', 'trigger', 'count', 'min before', 'median before', 'max before', 'avg after'], rows)
    out['compactions'] = [dict(seat=files[c['path']]['seat'], **{k: c[k] for k in ('ts', 'trigger', 'pre', 'post')}) for c in comp]

    # --- tools: what fills the context
    paths = tuple({r['path'] for r in reqs})
    tl = defaultdict(lambda: defaultdict(float))
    rr = dict(n=0, rep=0, chars=0)
    for i in range(0, len(paths), 500):
        chunk = paths[i:i + 500]
        q = ','.join('?' * len(chunk))
        for t in db.execute('select * from tools where path in (%s)' % q, chunk):
            x = tl[t['name']]
            x['calls'] += t['calls']
            x['chars'] += t['result_chars']
            x['carry'] += t['carry_char_requests']
        for f in db.execute('select n_reads, read_repeat_n, read_repeat_chars from files where path in (%s)' % q, chunk):
            rr['n'] += f['n_reads']
            rr['rep'] += f['read_repeat_n']
            rr['chars'] += f['read_repeat_chars']
    CPT = 3.2  # chars per token for tool output, rough
    bash = {k[5:]: v for k, v in tl.items() if k.startswith('bash:')}
    pseudo = {k: v for k, v in tl.items() if k.startswith('(')}
    for k in list(tl):
        if k.startswith('bash:') or k.startswith('('):
            del tl[k]
    for v in pseudo.values():  # these were stored as tokens * 4 or plain chars
        pass
    tcarry = sum(x['carry'] for x in tl.values()) / CPT
    rows = [[k, int(x['calls']), fmt(x['chars'] / CPT), fmt(x['chars'] / CPT / max(1, x['calls'])), fmt(x['carry'] / CPT), '%.1f%%' % (100 * x['carry'] / CPT / tot['cr'])]
            for k, x in sorted(tl.items(), key=lambda kv: -kv[1]['carry'])[:14]]
    rows.append(['all tools', int(sum(x['calls'] for x in tl.values())), fmt(sum(x['chars'] for x in tl.values()) / CPT), '', fmt(tcarry), '%.1f%%' % (100 * tcarry / tot['cr'])])
    mo = pseudo.get('(model output: text, tool calls, thinking)', {})
    tp = pseudo.get('(turn prompts: briefs, messages, notices)', {})
    rows.append(['model output kept in the prompt', int(mo.get('calls', 0)), fmt(mo.get('chars', 0) / 4), '', fmt(mo.get('carry', 0) / 4), '%.1f%%' % (100 * mo.get('carry', 0) / 4 / tot['cr'])])
    rows.append(['turn prompts (briefs, messages, notices)', int(tp.get('calls', 0)), fmt(tp.get('chars', 0) / CPT), fmt(tp.get('chars', 0) / CPT / max(1, tp.get('calls', 0))), fmt(tp.get('carry', 0) / CPT), '%.1f%%' % (100 * tp.get('carry', 0) / CPT / tot['cr'])])
    out['carry'] = dict(tools=tcarry, model_output=mo.get('carry', 0) / 4, turn_prompts=tp.get('carry', 0) / CPT)
    table('Tool results: size, and tokens re-read because the result stays in the prompt (whole files of sessions active in the window; tokens = chars / 3.2, rough)',
          ['tool', 'calls', 'result tokens', 'avg per call', 'tokens re-read later', 'share of cache read'], rows)
    out['tools'] = {k: dict(v) for k, v in tl.items()}
    bt = sum(x['carry'] for x in bash.values()) or 1
    def bgroup(h):
        w = h.split()[0] if h else '?'
        if w in ('cat', 'sed', 'head', 'tail', 'wc', 'awk', 'less', 'nl'):
            return 'read a file with cat, sed, head, tail, wc'
        if w in ('grep', 'rg', 'find', 'ls', 'which', 'fd'):
            return 'search and list (grep, ls, find)'
        if w == 'git':
            return 'git'
        if w == 'gh':
            return 'GitHub CLI'
        if w in ('ledger', 'coordinator', 'agent-traces', 'L(){', 'L()') or 'ledger' in h:
            return 'ledger and coordinator CLIs'
        if w in ('python3', 'python', 'node', 'for', 'bash', 'sh', 'jq'):
            return 'inline scripts and loops'
        if w in ('kgate', 'kubectl', 'ssh', 'curl'):
            return 'remote: kgate, kubectl, ssh, curl'
        if w in ('npm', 'pnpm', 'npx', 'bun', 'cargo', 'mix', 'uv', 'make', 'pytest'):
            return 'build and test runners'
        return 'other'
    bg = defaultdict(lambda: defaultdict(float))
    for h, x in bash.items():
        g = bg[bgroup(h)]
        for f in ('calls', 'chars', 'carry'):
            g[f] += x[f]
    table('Bash calls by kind of command',
          ['kind', 'calls', 'result tokens', 'avg per call', 'tokens re-read later', 'share of Bash re-read'],
          [[k, int(x['calls']), fmt(x['chars'] / CPT), fmt(x['chars'] / CPT / max(1, x['calls'])), fmt(x['carry'] / CPT), '%.0f%%' % (100 * x['carry'] / bt)]
           for k, x in sorted(bg.items(), key=lambda kv: -kv[1]['carry'])])
    out['bash_kinds'] = {k: dict(v) for k, v in bg.items()}
    out['tool_carry_share'] = tcarry / tot['cr']
    print('\nRead calls %d, of which repeats of the same file and range in one session: %d (%.0f%%), about %s tokens returned again' % (
        rr['n'], rr['rep'], 100 * rr['rep'] / max(1, rr['n']), fmt(rr['chars'] / 4)))
    out['repeat_reads'] = rr

    # --- hooks
    hk = defaultdict(lambda: defaultdict(float))
    for i in range(0, len(paths), 500):
        chunk = paths[i:i + 500]
        q = ','.join('?' * len(chunk))
        for h in db.execute('select * from hooks where path in (%s)' % q, chunk):
            x = hk[h['event']]
            x['n'] += h['n']
            x['chars'] += h['chars']
    table('Hook text added to the prompt', ['hook event', 'times', 'tokens added (chars / 4)', 'avg'],
          [[k, int(x['n']), fmt(x['chars'] / 4), fmt(x['chars'] / 4 / max(1, x['n']))] for k, x in sorted(hk.items(), key=lambda kv: -kv[1]['chars'])])
    out['hooks'] = {k: dict(v) for k, v in hk.items()}

    # --- Agent-tool helpers
    subs = defaultdict(lambda: defaultdict(float))
    for p, rs in sess.items():
        f = files[p]
        if not f['is_sub']:
            continue
        k = (f['root_seat'] or '?', f['seat'])
        x = subs[k]
        x['sessions'] += 1
        x['n'] += len(rs)
        x['usd'] += sum(r['usd'] for r in rs)
        x['cr'] += sum(r['cr'] for r in rs)
        x['first'] += (first_ctx.get(p) or (0,))[0]
        x['out'] += sum(r['out'] for r in rs)
    table('Agent-tool helpers by who started them', ['started by', 'helper seat', 'helpers', 'requests', 'avg requests', 'avg first prompt', 'cache read', 'list $'],
          [[k[0], k[1], int(x['sessions']), int(x['n']), '%.0f' % (x['n'] / x['sessions']), fmt(x['first'] / x['sessions']), fmt(x['cr']), '$%.0f' % x['usd']]
           for k, x in sorted(subs.items(), key=lambda kv: -kv[1]['usd'])[:16]])
    out['helpers'] = {'%s|%s' % k: dict(v) for k, v in subs.items()}

    # --- sessions per seat
    rows = []
    for s in seats:
        ps = [p for p in sess if files[p]['seat'] == s]
        n = [len(sess[p]) for p in ps]
        u = sorted(sum(r['usd'] for r in sess[p]) for p in ps)
        rows.append([s, len(ps), '%.0f' % (sum(n) / len(n)), max(n), '$%.2f' % u[len(u) // 2], '$%.2f' % u[-1], '$%.0f' % sum(u)])
    table('Sessions by seat', ['seat', 'sessions', 'avg requests', 'max requests', 'median list $', 'max list $', 'total list $'], rows)

    # --- output and thinking
    d = agg(lambda r: r['seat'] + ' / ' + r['model'].replace('claude-', '') + ' ' + str(r['effort']))
    table('Output and thinking', ['seat / model effort', 'requests', 'output', 'thinking', 'thinking share', 'output per request'],
          [[k, int(x['n']), fmt(x['out']), fmt(x['think']), '%.0f%%' % (100 * x['think'] / max(1, x['out'])), fmt(x['out'] / x['n'])]
           for k, x in sorted(d.items(), key=lambda kv: -kv[1]['out'])[:14]])
    adv = [r for r in reqs if r['adv_n']]
    print('\nadvisor calls: %d requests, %s advisor input tokens, %s advisor output tokens (not in the usage totals above)' % (
        len(adv), fmt(sum(r['adv_in'] for r in adv)), fmt(sum(r['adv_out'] for r in adv))))
    am = defaultdict(lambda: defaultdict(float))
    for r in adv:
        k = (r['seat'], (r['advisor_model'] or '?').replace('claude-', ''))
        x = am[k]
        x['calls'] += r['adv_n']
        x['inp'] += r['adv_in']
        x['out'] += r['adv_out']
        ar = RATES.get(r['advisor_model'] or '', RATES['claude-opus-5-5'])
        x['usd'] += r['adv_in'] * ar[0] / 1e6 + r['adv_out'] * ar[1] / 1e6
    au = sum(x['usd'] for x in am.values())
    table('Advisor tool calls (a second, stronger model is sent the whole transcript; billed outside the totals above)',
          ['seat', 'advisor model', 'calls', 'input (all uncached)', 'avg input per call', 'output', 'list $'],
          [[k[0], k[1], int(x['calls']), fmt(x['inp']), fmt(x['inp'] / x['calls']), fmt(x['out']), '$%.0f' % x['usd']] for k, x in sorted(am.items(), key=lambda kv: -kv[1]['usd'])]
          + [['all', '', int(sum(x['calls'] for x in am.values())), fmt(sum(x['inp'] for x in am.values())), '', fmt(sum(x['out'] for x in am.values())), '$%.0f = %.0f%% on top of the total' % (au, 100 * au / T)]])
    out['advisor'] = dict(n=len(adv), inp=sum(r['adv_in'] for r in adv), out=sum(r['adv_out'] for r in adv), usd=au,
                          by={'%s|%s' % k: dict(v) for k, v in am.items()})

    # --- what-if: compact earlier. Replays each session; when the prompt reaches the
    # limit it is cut to FLOOR and later prompts shrink by the same amount until the
    # real compaction. Charges each extra compaction one full read of the prompt plus
    # a fresh write of FLOOR. Does not model re-reading files after a compaction.
    FLOOR = 85_500  # measured: average prompt on the first request after a real auto compaction
    sim_rows = []
    out['compact_sim'] = {}
    for limit in (300_000, 200_000, 150_000, 100_000):
        res = defaultdict(lambda: defaultdict(float))
        for p, rs in sess.items():
            d = 0
            prev = None
            seat = files[p]['seat']
            for r in rs:
                if prev is not None and r['ctx'] < 0.6 * prev:
                    d = 0
                prev = r['ctx']
                c2 = r['ctx'] - d
                if c2 >= limit:
                    ri, ro, rr_, r5, r1 = rate(r['model'], r['ctx'])
                    res[seat]['extra'] += 1
                    res[seat]['cost'] += (c2 * rr_ + FLOOR * (r1 if r['cache_ttl'] == '1h' else r5) + 6000 * ro) / 1e6
                    d += c2 - FLOOR
                    c2 = FLOOR
                if d:
                    ri, ro, rr_, r5, r1 = rate(r['model'], r['ctx'])
                    saved = min(d, r['cr'])
                    res[seat]['tok'] += saved
                    res[seat]['usd'] += saved * rr_ / 1e6
        tt = sum(x['tok'] for x in res.values())
        tu = sum(x['usd'] - x['cost'] for x in res.values())
        te = sum(x['extra'] for x in res.values())
        top = sorted(res.items(), key=lambda kv: -(kv[1]['usd'] - kv[1]['cost']))[:4]
        sim_rows.append([fmt(limit), fmt(tt), '%.0f%%' % (100 * tt / tot['cr']), int(te), '$%.0f (%.0f%%)' % (tu, 100 * tu / T),
                         ', '.join('%s $%.0f' % (k, x['usd'] - x['cost']) for k, x in top)])
        out['compact_sim'][str(limit)] = dict(tokens=tt, net_usd=tu, extra=te, by_seat={k: dict(v) for k, v in res.items()})
    table('What-if: compact at a lower prompt size (today: 467K)', ['limit', 'cache read avoided', 'share of cache read', 'extra compactions', 'net list $ in window', 'where'], sim_rows)

    # --- review machinery by role
    rv = defaultdict(lambda: defaultdict(float))
    for p, rs in sess.items():
        f = files[p]
        if f['seat'] != 'reviewer':
            continue
        sl = (f['seat_line'] or '').lower()
        low = (f['first_prompt'] or '').lower()
        role = 'reviewer'
        for k, name in (('label', 'labeller'), ('judge', 'churn judge'), ('compar', 'comparer'), ('blind', 'blind designer'), ('intent', 'intent checker'), ('scorer', 'scorer')):
            if k in sl or k in low[:120]:
                role = name
                break
        x = rv[(role, rs[0]['model'].replace('claude-', ''))]
        x['sessions'] += 1
        x['n'] += len(rs)
        x['usd'] += sum(r['usd'] for r in rs)
        x['cw'] += sum(r['cw1h'] + r['cw5m'] for r in rs)
        x['out'] += sum(r['out'] for r in rs)
        x['cr'] += sum(r['cr'] for r in rs)
    table('Review sessions by role', ['role', 'model', 'sessions', 'avg requests', 'cache write', 'cache read', 'output', 'list $', '$ per session'],
          [[k[0], k[1], int(x['sessions']), '%.0f' % (x['n'] / x['sessions']), fmt(x['cw']), fmt(x['cr']), fmt(x['out']), '$%.0f' % x['usd'], '$%.2f' % (x['usd'] / x['sessions'])]
           for k, x in sorted(rv.items(), key=lambda kv: -kv[1]['usd'])])
    out['review_roles'] = {'%s|%s' % k: dict(v) for k, v in rv.items()}

    # --- biggest sessions
    rows = []
    big = sorted(sess.items(), key=lambda kv: -sum(r['usd'] for r in kv[1]))[:15]
    for p, rs in big:
        f = files[p]
        rows.append([f['seat'], rs[0]['model'].replace('claude-', ''), len(rs), fmt(sum(r['ctx'] for r in rs) / len(rs)), fmt(max(r['ctx'] for r in rs)),
                     fmt(sum(r['cr'] for r in rs)), '$%.0f' % sum(r['usd'] for r in rs), (f['first_prompt'] or '')[:60].replace('\n', ' ').replace('|', '/')])
    table('Fifteen most expensive sessions in the window', ['seat', 'model', 'requests', 'avg prompt', 'max prompt', 'cache read', 'list $', 'brief starts'], rows)
    top15 = sum(sum(r['usd'] for r in rs) for p, rs in big)
    print('\ntop 15 sessions: $%.0f, %.0f%% of the window' % (top15, 100 * top15 / T))
    out['top15_share'] = top15 / T
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=1, default=str)


if __name__ == '__main__':
    main()
