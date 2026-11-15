#!/usr/bin/env python3
"""Collect token usage from Claude Code transcripts into a small sqlite file.

Reads ~/.claude/projects/**/*.jsonl (read-only) and writes numbers only
(plus a 200-char prefix of each session's first prompt, used to name the seat)
to OUT/usage.sqlite. No transcript content is copied.

Usage: collect.py [OUT_DIR]   (default: ~/.local/state/token-efficiency)

Counting rules (see README.md):
- One API request = one assistant message id. Streaming writes several records
  per id with the same usage; the last one wins. An id seen in more than one
  file (resumed or forked sessions copy history) is counted once, in the file
  where it appears with the earliest timestamp.
- Token kinds are kept apart: fresh input, cache write (1h, 5m), cache read,
  output. Nothing is summed across kinds here.
"""
import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool

ROOT = os.path.expanduser('~/.claude/projects')
# Where usage.sqlite lives. The source folder is managed by chezmoi, so the database is kept outside it.
STATE_DIR = os.path.expanduser('~/.local/state/token-efficiency')
SEAT_RE = re.compile(r'Seat:\s*\**\s*([A-Za-z][A-Za-z -]{1,24}?)\s*[\.\(\n,;:]')


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get('type') == 'text':
                    out.append(b.get('text') or '')
    return '\n'.join(out)


def result_chars(content):
    if isinstance(content, str):
        return len(content)
    n = 0
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get('type') == 'text':
                    n += len(b.get('text') or '')
                elif b.get('type') == 'image':
                    n += 6000  # rough: an image is ~1.5K tokens
                else:
                    n += len(json.dumps(b))
    return n


BASH_SKIP = re.compile(r'^(cd|export|set|source|\.|nice|time|timeout|sudo|env|command|exec|\(|\{|[A-Za-z_][A-Za-z0-9_]*=\S*)$')


def bash_head(cmd):
    """First real command word of a shell line: `cd x && FOO=1 git status` -> git status."""
    cmd = cmd.strip()
    parts = re.split(r'&&|;|\n|\|\|', cmd)
    for part in parts:
        words = part.strip().split()
        while words and (BASH_SKIP.match(words[0]) or words[0].startswith('-')):
            if words[0] in ('cd', 'export', 'source', '.', 'set'):
                words = []
                break
            words = words[1:]
        if not words:
            continue
        w = os.path.basename(words[0])
        if w in ('node', 'python3', 'python', 'bash', 'sh', 'npx', 'pnpm', 'npm', 'bun', 'uv'):
            for x in words[1:]:
                if not x.startswith('-'):
                    return w + ' ' + os.path.basename(x)[:30]
            return w
        if w in ('git', 'gh', 'kubectl', 'kgate', 'sqlite3', 'docker', 'systemctl', 'cargo', 'mix', 'chezmoi', 'viz', 'op', 'ssh') and len(words) > 1:
            return w + ' ' + words[1][:20]
        return w[:30]
    return '?'


def scan(path):
    rel = os.path.relpath(path, ROOT)
    parts = rel.split(os.sep)
    is_sub = 'subagents' in parts
    parent = parts[1] if is_sub and len(parts) > 2 else None
    meta = dict(path=rel, project=parts[0], is_sub=int(is_sub), parent=parent,
                session=None, entrypoint=None, cwd=None, first_prompt=None,
                agent_type=None, human_turns=0)
    reqs = {}          # msgid -> row dict
    order = []         # msgids in first-seen order
    turns = []         # dict(origin, source, prefix, ts, reqs=[msgid])
    compactions = []
    tool_name = {}     # tool_use_id -> (name, key)
    tool_calls = Counter()
    tool_result_chars = Counter()
    tool_carry = Counter()   # name -> chars * later requests in this file segment
    pending_results = []     # (name, chars, n_requests_seen_at_time)
    read_paths = Counter()
    read_repeat_chars = 0
    read_repeat_n = 0
    hook_chars = Counter()
    hook_n = Counter()
    shapes = {}
    shape_use = Counter()
    cost_states = {}
    qsrc = Counter()
    seg_bounds = []
    nreq_seen = 0
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
        if meta['session'] is None and d.get('sessionId'):
            meta['session'] = d['sessionId']
        if meta['entrypoint'] is None and d.get('entrypoint'):
            meta['entrypoint'] = d['entrypoint']
            meta['cwd'] = d.get('cwd')
        if t == 'assistant':
            m = d.get('message') or {}
            mid = m.get('id')
            model = m.get('model')
            u = m.get('usage') or {}
            if not mid or model == '<synthetic>':
                continue
            cc = u.get('cache_creation') or {}
            cw = u.get('cache_creation_input_tokens') or 0
            cw1h = cc.get('ephemeral_1h_input_tokens') or 0
            cw5m = cc.get('ephemeral_5m_input_tokens') or 0
            if cw and not (cw1h or cw5m):
                if d.get('promptCacheRequested') == '1h':
                    cw1h = cw
                else:
                    cw5m = cw
            adv_in = adv_out = adv_n = 0
            adv_model = None
            for it in u.get('iterations') or []:
                if it.get('type') == 'advisor_message':
                    adv_n += 1
                    adv_model = it.get('model') or adv_model
                    adv_in += (it.get('input_tokens') or 0) + (it.get('cache_read_input_tokens') or 0) + (it.get('cache_creation_input_tokens') or 0)
                    adv_out += it.get('output_tokens') or 0
            row = dict(msgid=mid, ts=d.get('timestamp'), model=model,
                       inp=u.get('input_tokens') or 0, cw1h=cw1h, cw5m=cw5m,
                       cr=u.get('cache_read_input_tokens') or 0,
                       out=u.get('output_tokens') or 0,
                       think=(u.get('output_tokens_details') or {}).get('thinking_tokens') or 0,
                       effort=d.get('effort'), cache_ttl=d.get('promptCacheRequested'),
                       adv_n=adv_n, adv_in=adv_in, adv_out=adv_out,
                       advisor_model=adv_model or d.get('advisorModel'),
                       after_compact=0)
            if mid not in reqs:
                order.append(mid)
                nreq_seen += 1
                if turns:
                    turns[-1]['reqs'].append(mid)
            else:
                row['after_compact'] = reqs[mid]['after_compact']
            reqs[mid] = row
            for b in m.get('content') or []:
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    name = b.get('name') or '?'
                    if name.startswith('mcp__'):
                        short = '__'.join(name.split('__')[:2]) + '__*'
                    else:
                        short = name
                    key = None
                    if name == 'Bash':
                        short = 'Bash'
                        key = 'bash:' + bash_head((b.get('input') or {}).get('command') or '')
                    if name == 'Read':
                        inp = b.get('input') or {}
                        key = '%s|%s|%s' % (inp.get('file_path'), inp.get('offset'), inp.get('limit'))
                    if b.get('id') not in tool_name:
                        tool_calls[short] += 1
                    tool_name[b.get('id')] = (short, key)
        elif t == 'user':
            m = d.get('message') or {}
            content = m.get('content')
            is_tool_result = False
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get('type') == 'tool_result':
                        is_tool_result = True
                        name, key = tool_name.get(b.get('tool_use_id'), ('?', None))
                        n = result_chars(b.get('content'))
                        tool_result_chars[name] += n
                        pending_results.append((name, n, nreq_seen))
                        if key and key.startswith('bash:'):
                            tool_calls[key] += 1
                            tool_result_chars[key] += n
                            pending_results.append((key, n, nreq_seen))
                            key = None
                        if key:
                            read_paths[key] += 1
                            if read_paths[key] > 1:
                                read_repeat_n += 1
                                read_repeat_chars += n
            if d.get('isCompactSummary'):
                continue
            if not is_tool_result and not d.get('isMeta'):
                txt = text_of(content)
                if meta['first_prompt'] is None and txt.strip():
                    meta['first_prompt'] = txt[:6000]
                origin = d.get('turnOrigin') or ('sub' if is_sub else 'unknown')
                if origin == 'human':
                    meta['human_turns'] += 1
                pending_results.append(('(turn prompts: briefs, messages, notices)', len(txt), nreq_seen))
                tool_result_chars['(turn prompts: briefs, messages, notices)'] += len(txt)
                tool_calls['(turn prompts: briefs, messages, notices)'] += 1
                turns.append(dict(origin=origin, source=d.get('promptSource'),
                                  prefix=txt.strip()[:160], ts=d.get('timestamp'), reqs=[]))
        elif t == 'system':
            if d.get('subtype') == 'compact_boundary':
                cm = d.get('compactMetadata') or {}
                compactions.append(dict(ts=d.get('timestamp'), trigger=cm.get('trigger'),
                                        pre=cm.get('preTokens') or 0, post=cm.get('postTokens') or 0))
                seg_bounds.append(nreq_seen)
                # tool results stop being carried at a compaction
                for name, n, at in pending_results:
                    tool_carry[name] += n * max(0, nreq_seen - at)
                pending_results = []
                # mark next request as post-compaction
                meta.setdefault('_mark_compact', True)
        elif t == 'attachment':
            a = d.get('attachment') or {}
            if a.get('type') == 'hook_success':
                ev = a.get('hookEvent') or '?'
                n = 0
                so = a.get('stdout') or ''
                try:
                    j = json.loads(so)
                    n = len(((j.get('hookSpecificOutput') or {}).get('additionalContext')) or '')
                except Exception:
                    n = len(so) if ev in ('SessionStart', 'UserPromptSubmit') else 0
                hook_chars[ev] += n
                hook_n[ev] += 1
            elif a.get('type') in ('hook_additional_context',):
                ev = a.get('hookEvent') or a.get('hookName') or '?'
                c = a.get('content')
                hook_chars[ev + ':ctx'] += len(json.dumps(c)) if c else 0
                hook_n[ev + ':ctx'] += 1
        elif t == 'api-request':
            shape_use[d.get('shapeHash')] += 1
            qsrc[d.get('querySource')] += 1
            if meta['agent_type'] is None and d.get('querySource'):
                meta['agent_type'] = d.get('querySource')
        elif t == 'api-request-shape':
            sh = d.get('shape') or {}
            sysc = sum(len(x.get('text') or '') for x in (sh.get('system') or []) if isinstance(x, dict))
            tl = sh.get('tools') or []
            per = {}
            for x in tl:
                if isinstance(x, dict):
                    per[x.get('name') or '?'] = len(json.dumps(x))
            shapes[d.get('shapeHash')] = dict(system_chars=sysc, tools_chars=sum(per.values()),
                                               n_tools=len(per), per_tool=per)
        elif t == 'cost-state':
            cost_states[d.get('startTime')] = dict(cost=d.get('totalCostUSD'), mu=d.get('modelUsage'))
        # mark first request after a compaction
        if meta.get('_mark_compact') and t == 'assistant':
            mid = (d.get('message') or {}).get('id')
            if mid in reqs:
                reqs[mid]['after_compact'] = 1
                meta.pop('_mark_compact', None)
    fh.close()
    for name, n, at in pending_results:
        tool_carry[name] += n * max(0, nreq_seen - at)
    meta.pop('_mark_compact', None)
    # the model's own output (text, tool calls, kept thinking) also stays in the prompt
    bounds = seg_bounds + [nreq_seen]
    bi = 0
    oc = 0
    for i, mid in enumerate(order):
        while bi < len(bounds) - 1 and i >= bounds[bi]:
            bi += 1
        oc += reqs[mid]['out'] * max(0, bounds[bi] - i - 1)
    name = '(model output: text, tool calls, thinking)'
    tool_carry[name] = oc * 4  # stored as chars like the others; analyze divides by 4
    tool_result_chars[name] = sum(r['out'] for r in reqs.values()) * 4
    tool_calls[name] = len(order)
    fp = meta['first_prompt'] or ''
    sm = SEAT_RE.search(fp[:6000])
    meta['seat_line'] = sm.group(1).strip().lower() if sm else None
    meta['first_prompt'] = fp[:200]
    return dict(meta=meta, reqs=[reqs[i] for i in order], turns=turns, compactions=compactions,
                tool_calls=dict(tool_calls), tool_result_chars=dict(tool_result_chars),
                tool_carry=dict(tool_carry), read_repeat_n=read_repeat_n,
                read_repeat_chars=read_repeat_chars, n_reads=sum(read_paths.values()),
                hook_chars=dict(hook_chars), hook_n=dict(hook_n), shapes=shapes,
                shape_use=dict(shape_use), cost_states=cost_states)


def main(out_dir=None):
    out_dir = out_dir or (sys.argv[1] if len(sys.argv) > 1 else STATE_DIR)
    os.makedirs(out_dir, exist_ok=True)
    db_path = os.path.join(out_dir, 'usage.sqlite')
    if os.path.exists(db_path):
        os.remove(db_path)
    db = sqlite3.connect(db_path)
    db.executescript('''
    create table files(path text primary key, project text, is_sub int, parent text, session text,
      entrypoint text, cwd text, first_prompt text, seat_line text, agent_type text, human_turns int,
      n_reads int, read_repeat_n int, read_repeat_chars int);
    create table requests(msgid text primary key, path text, seq int, ts text, model text,
      inp int, cw1h int, cw5m int, cr int, out int, think int, effort text, cache_ttl text,
      adv_n int, adv_in int, adv_out int, advisor_model text, after_compact int, turn int);
    create table turns(path text, turn int, origin text, source text, prefix text, ts text, n_reqs int);
    create table compactions(path text, ts text, trigger text, pre int, post int);
    create table tools(path text, name text, calls int, result_chars int, carry_char_requests int);
    create table hooks(path text, event text, n int, chars int);
    create table shapes(hash text primary key, system_chars int, tools_chars int, n_tools int, per_tool text);
    create table shape_use(path text, hash text, n int);
    create table cost_states(path text, start_time text, cost real, model text, inp int, out int, cr int, cw int, cw5m int, cw1h int, model_cost real);
    create table dupes(msgid text, path text);
    ''')
    files = sorted(glob.glob(os.path.join(ROOT, '**', '*.jsonl'), recursive=True))
    seen = {}
    pending = []
    with Pool(max(2, (os.cpu_count() or 4) - 1)) as pool:
        for r in pool.imap_unordered(scan, files, chunksize=4):
            if not r:
                continue
            pending.append(r)
    # decide the owner file of every message id: earliest timestamp wins
    for r in pending:
        p = r['meta']['path']
        for q in r['reqs']:
            k = q['msgid']
            cur = seen.get(k)
            if cur is None or (q['ts'] or '') < cur[0] or ((q['ts'] or '') == cur[0] and p < cur[1]):
                seen[k] = (q['ts'] or '', p)
    for r in pending:
        m = r['meta']
        p = m['path']
        db.execute('insert into files values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (p, m['project'], m['is_sub'], m['parent'], m['session'], m['entrypoint'], m['cwd'],
                    m['first_prompt'], m['seat_line'], m['agent_type'], m['human_turns'],
                    r['n_reads'], r['read_repeat_n'], r['read_repeat_chars']))
        turn_of = {}
        for i, t in enumerate(r['turns']):
            for mid in t['reqs']:
                turn_of[mid] = i
            db.execute('insert into turns values(?,?,?,?,?,?,?)',
                       (p, i, t['origin'], t['source'], t['prefix'], t['ts'], len(t['reqs'])))
        for seq, q in enumerate(r['reqs']):
            if seen[q['msgid']][1] != p:
                db.execute('insert into dupes values(?,?)', (q['msgid'], p))
                continue
            db.execute('insert into requests values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (q['msgid'], p, seq, q['ts'], q['model'], q['inp'], q['cw1h'], q['cw5m'], q['cr'],
                        q['out'], q['think'], q['effort'], q['cache_ttl'], q['adv_n'], q['adv_in'],
                        q['adv_out'], q['advisor_model'], q['after_compact'], turn_of.get(q['msgid'], -1)))
        for c in r['compactions']:
            db.execute('insert into compactions values(?,?,?,?,?)', (p, c['ts'], c['trigger'], c['pre'], c['post']))
        names = set(r['tool_calls']) | set(r['tool_result_chars'])
        for n in names:
            db.execute('insert into tools values(?,?,?,?,?)',
                       (p, n, r['tool_calls'].get(n, 0), r['tool_result_chars'].get(n, 0), r['tool_carry'].get(n, 0)))
        for ev, n in r['hook_n'].items():
            db.execute('insert into hooks values(?,?,?,?)', (p, ev, n, r['hook_chars'].get(ev, 0)))
        for h, s in r['shapes'].items():
            db.execute('insert or ignore into shapes values(?,?,?,?,?)',
                       (h, s['system_chars'], s['tools_chars'], s['n_tools'], json.dumps(s['per_tool'])))
        for h, n in r['shape_use'].items():
            db.execute('insert into shape_use values(?,?,?)', (p, h, n))
        for st, c in r['cost_states'].items():
            for model, v in (c['mu'] or {}).items():
                db.execute('insert into cost_states values(?,?,?,?,?,?,?,?,?,?,?)',
                           (p, str(st), c['cost'], model, v.get('inputTokens'), v.get('outputTokens'),
                            v.get('cacheReadInputTokens'), v.get('cacheCreationInputTokens'),
                            v.get('cacheCreationEphemeral5mInputTokens'), v.get('cacheCreationEphemeral1hInputTokens'),
                            v.get('costUSD')))
    db.executescript('''
    create index r_path on requests(path, seq);
    create index r_ts on requests(ts);
    ''')
    db.commit()
    n = db.execute('select count(*), sum(inp), sum(cw1h), sum(cw5m), sum(cr), sum(out) from requests').fetchone()
    d = db.execute('select count(*) from dupes').fetchone()[0]
    print('files', len(pending), 'requests', n[0], 'dupes dropped', d)
    print('input', n[1], 'cache write 1h', n[2], 'cache write 5m', n[3], 'cache read', n[4], 'output', n[5])
    print('wrote', db_path)


if __name__ == '__main__':
    main()
