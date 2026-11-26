#!/usr/bin/env python3
"""design_matrix.py FILE [--label TEXT] [--json] [--out PATH]: check, classify and render one Axiomatic Design matrix.

FILE is a markdown file (or JSON, see below) with three tables. Table headers are case-insensitive; the sections are `## FRs`,
`## DPs` and `## X`. Cells hold no `|`.

    ## FRs
    | id  | text                                  | dp  |
    | FR1 | keep a run's record intact on a crash | DP1 |
    | FR2 | advance a run only on a verdict       | DP2 |

    ## DPs
    | id  | text                    | parts                     |
    | DP1 | append-only run journal | src/journal.py            |
    | DP2 | verdict gate            | src/gate.py; src/runs.py  |

    ## X
    | fr  | dp  | reason                                  | evidence             |
    | FR1 | DP2 | tuning the gate changes what is written | src/gate.py:88       |

* FRs: `dp` names the DP that delivers the FR. An empty `dp` is an FR with no DP (unmet). Two FRs may name one DP.
* DPs: `parts` (optional) lists the files or modules of the DP, split on `;`. A part in several DPs is reported, not judged.
* X: one row per off-diagonal cell, "changing DP `dp` to tune its own FR forces a change to keep FR `fr` met". This rule is
  this skill's convention, not Suh's. `reason` is one line. `evidence` is one or more of (split on `;`, `,` or space):
  `path:line` (or `path:3-9`), `cochange:<fileA>+<fileB>`, `commit:<hex sha>`, a finding id (`F-3`, `DF-2`, `U-1`).
  The diagonal (an FR and its own DP) is implied and may not be listed. An import alone is not evidence.

JSON input: {"frs": [{"id", "text", "dp"}], "dps": [{"id", "text", "parts": []}], "x": [{"fr", "dp", "reason", "evidence"}]}.

Output: a markdown block to paste into DESIGN.md (`--json` prints the same facts as JSON instead). Exit 0 when the input is valid,
whatever the class (a coupled matrix is a finding, not an error); 1 when the input is invalid (the errors are printed); 2 on usage.

The matrix is square when the FRs and DPs pair one-to-one. Then it is uncoupled (no X), decoupled (the DP graph has no cycle:
the DP order is a topological sort, ties broken by id) or coupled (the cycles are the strongly connected components, found with
repo_facts.py's `scc_components`). Otherwise it is not classified: the theorem that applies is printed (Suh 1996, App. 1-A).
The result does not depend on the order of the rows in the file.
"""
import argparse
import heapq
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from runlog import log_run  # noqa: E402

ID_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_.-]*$')
EVIDENCE_KINDS = (
    ('path:line', re.compile(r'^[^\s:]+:\d+(-\d+)?$')),
    ('cochange', re.compile(r'^cochange:[^\s+]+\+[^\s+]+$')),
    ('commit', re.compile(r'^commit:[0-9a-f]{7,40}$')),
    ('finding id', re.compile(r'^(DF|F|U)-\d+$')),
)
EVIDENCE_HELP = 'path:line, cochange:<a>+<b>, commit:<hex sha> or a finding id (F-n, DF-n, U-n)'


def load_scc():
    """repo_facts.scc_components, loaded by path as the other skills' scripts do."""
    path = os.path.join(HERE, 'repo_facts.py')
    if not os.path.isfile(path):
        sys.stderr.write('design_matrix: repo_facts.py not found at %s\n' % path)
        sys.exit(2)
    spec = importlib.util.spec_from_file_location('repo_facts', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scc_components


def natural(text):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', text)]


# --- input ----------------------------------------------------------------

def split_row(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def parse_markdown(text):
    """{'FRs': [row dicts], 'DPs': [...], 'X': [...]} from the three tables; raises ValueError."""
    tables, current, header = {}, None, None
    for line in text.splitlines():
        stripped = line.strip()
        head = re.match(r'^#{1,6}\s*(FRs?|DPs?|X)\b', stripped, re.I)
        if head:
            key = head.group(1).upper()
            current = 'X' if key == 'X' else key[:2] + 's'
            tables[current] = []
            header = None
            continue
        if current is None or not stripped.startswith('|'):
            continue
        cells = split_row(stripped)
        if all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c) and any(cells):
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if len(cells) != len(header):
            raise ValueError('%s table: row has %d cells, header has %d: %s' % (current, len(cells), len(header), stripped))
        tables[current].append(dict(zip(header, cells)))
    missing = [k for k in ('FRs', 'DPs') if k not in tables]
    if missing:
        raise ValueError('no `## %s` section found' % '` or `## '.join(missing))
    tables.setdefault('X', [])
    return {'frs': tables['FRs'], 'dps': tables['DPs'], 'x': tables['X']}


def load(path):
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    if text.lstrip().startswith('{'):
        data = json.loads(text)
        return {k: data.get(k, []) for k in ('frs', 'dps', 'x')}
    return parse_markdown(text)


def clean(value):
    return value.strip() if isinstance(value, str) else ''


def validate(data):
    """(model, errors). The model holds cleaned rows; errors are strings, all of them, in a stable order."""
    errors = []
    frs, dps, xs = [], [], []
    for kind, rows, out in (('FR', data['frs'], frs), ('DP', data['dps'], dps)):
        seen = set()
        for i, row in enumerate(rows, 1):
            rid = clean(row.get('id'))
            if not ID_RE.match(rid):
                errors.append('%s row %d: id %r is empty or not a plain id' % (kind, i, rid))
                continue
            if rid in seen:
                errors.append('%s %s: listed twice' % (kind, rid))
                continue
            seen.add(rid)
            item = {'id': rid, 'text': clean(row.get('text'))}
            if not item['text']:
                errors.append('%s %s: text is empty' % (kind, rid))
            if kind == 'FR':
                item['dp'] = clean(row.get('dp'))
            else:
                parts = row.get('parts') or []
                if isinstance(parts, str):
                    parts = parts.split(';')
                item['parts'] = sorted({p.strip() for p in parts if p.strip()})
            out.append(item)
    dp_ids = {d['id'] for d in dps}
    fr_ids = {f['id'] for f in frs}
    for f in frs:
        if f['dp'] and f['dp'] not in dp_ids:
            errors.append('FR %s: dp %s is not in the DP table' % (f['id'], f['dp']))
    own = {f['id']: f['dp'] for f in frs}
    seen_cells = set()
    for i, row in enumerate(data['x'], 1):
        fr, dp = clean(row.get('fr')), clean(row.get('dp'))
        where = 'X row %d (%s, %s)' % (i, fr, dp)
        if fr not in fr_ids or dp not in dp_ids:
            errors.append('%s: %s is not in the %s table' % (where, fr if fr not in fr_ids else dp, 'FR' if fr not in fr_ids else 'DP'))
            continue
        if own.get(fr) == dp:
            errors.append('%s: FR %s is delivered by %s; the diagonal is implied, do not list it' % (where, fr, dp))
            continue
        if (fr, dp) in seen_cells:
            errors.append('%s: listed twice' % where)
            continue
        seen_cells.add((fr, dp))
        reason, evidence = clean(row.get('reason')), clean(row.get('evidence'))
        if not reason:
            errors.append('%s: reason is missing' % where)
        elif '\n' in reason:
            errors.append('%s: reason is more than one line' % where)
        tokens = [t for t in re.split(r'[;,\s]+', evidence) if t]
        if not tokens:
            errors.append('%s: evidence is missing; give %s' % (where, EVIDENCE_HELP))
        for token in tokens:
            if not any(rx.match(token) for _, rx in EVIDENCE_KINDS):
                errors.append('%s: evidence %r is none of %s' % (where, token, EVIDENCE_HELP))
        xs.append({'fr': fr, 'dp': dp, 'reason': reason, 'evidence': tokens})
    return {'frs': frs, 'dps': dps, 'x': xs}, errors


# --- analysis -------------------------------------------------------------

def topo_blocks(nodes, edges, scc_components):
    """(blocks, coupled): blocks is the ordered list of node groups (a cycle is one group), sources first, ties by natural id."""
    comps = scc_components(set(nodes), edges)
    block_of = {n: [n] for n in nodes}
    for comp in comps:
        for n in comp:
            block_of[n] = comp
    key = {id(b): b for b in block_of.values()}
    names = {id(b): tuple(sorted(b, key=natural)) for b in key.values()}
    succ = {i: set() for i in key}
    indeg = {i: 0 for i in key}
    for a, b in edges:
        ia, ib = id(block_of[a]), id(block_of[b])
        if ia != ib and ib not in succ[ia]:
            succ[ia].add(ib)
            indeg[ib] += 1
    heap = [(natural(names[i][0]), i) for i in key if indeg[i] == 0]
    heapq.heapify(heap)
    order = []
    while heap:
        _, i = heapq.heappop(heap)
        order.append(list(names[i]))
        for j in sorted(succ[i]):
            indeg[j] -= 1
            if indeg[j] == 0:
                heapq.heappush(heap, (natural(names[j][0]), j))
    return order, [sorted(c, key=natural) for c in comps]


def analyse(model, scc_components):
    frs = sorted(model['frs'], key=lambda f: natural(f['id']))
    dps = sorted(model['dps'], key=lambda d: natural(d['id']))
    delivers = {}
    for f in frs:
        if f['dp']:
            delivers.setdefault(f['dp'], []).append(f['id'])
    unmet = [f['id'] for f in frs if not f['dp']]
    removal = [d['id'] for d in dps if d['id'] not in delivers]
    shared = {d: sorted(v, key=natural) for d, v in delivers.items() if len(v) > 1}
    part_use = {}
    for d in dps:
        for p in d['parts']:
            part_use.setdefault(p, []).append(d['id'])
    parts_shared = {p: v for p, v in sorted(part_use.items()) if len(v) > 1}
    res = {'frs': frs, 'dps': dps, 'x': sorted(model['x'], key=lambda c: (natural(c['fr']), natural(c['dp']))),
           'unmet_frs': unmet, 'removal_candidates': removal, 'dps_serving_several_frs': shared,
           'parts_in_several_dps': parts_shared}
    n_fr, n_dp = len(frs), len(dps)
    if n_fr == n_dp and not unmet and not shared:
        pair = {f['dp']: f['id'] for f in frs}  # DP id -> its FR
        edges = [(c['dp'], next(f['dp'] for f in frs if f['id'] == c['fr'])) for c in res['x']]
        blocks, coupled = topo_blocks([d['id'] for d in dps], edges, scc_components)
        res['pair'] = pair
        res['order'] = [dp for block in blocks for dp in block]
        res['blocks'] = coupled
        res['theorem'] = None
        if coupled:
            res['class'] = 'coupled'
        elif edges:
            res['class'] = 'decoupled'
        else:
            res['class'] = 'uncoupled'
        return res
    res['class'] = 'not classified'
    res['order'] = [d['id'] for d in dps]
    res['blocks'] = []
    if n_dp < n_fr:
        res['theorem'] = ('%d DPs for %d FRs. Theorem 1 (Suh 1996, App. 1-A): with fewer DPs than FRs, either a coupled design '
                          'results or the FRs cannot be satisfied.' % (n_dp, n_fr))
    elif n_dp > n_fr:
        res['theorem'] = ('%d DPs for %d FRs. Theorem 3: with more DPs than FRs, the design is redundant or coupled.' % (n_dp, n_fr))
    else:
        res['theorem'] = ('%d DPs for %d FRs, but they do not pair one-to-one (an FR with no DP, or one DP delivering several FRs). '
                          'Theorem 4: an ideal design has as many DPs as FRs, one each.' % (n_dp, n_fr))
    return res


# --- output ---------------------------------------------------------------

def cell(text):
    return text.replace('|', '\\|')


def render(res, label):
    out = ['#### %s' % label, '']
    cls = res['class']
    if cls == 'not classified':
        out += ['Classification: not classified (the matrix is not square). %s' % res['theorem'], '']
    elif cls == 'uncoupled':
        out += ['Classification: uncoupled. Every FR has its own DP and no off-diagonal X; the DPs can be set in any order.', '']
    elif cls == 'decoupled':
        out += ['Classification: decoupled. DP order (set earlier ones first): %s.' % ' -> '.join(res['order']), '']
    else:
        blocks = '; '.join('{%s}' % ', '.join(b) for b in res['blocks'])
        out += ['Classification: coupled. Coupled blocks (strongly connected): %s. Order of the DPs, with each block kept together: '
                '%s.' % (blocks, ' -> '.join(res['order'])), '']
    pair = res.get('pair')
    rows = [pair[d] for d in res['order']] if pair else [f['id'] for f in res['frs']]
    cols = list(res['order'])
    own = {f['id']: f['dp'] for f in res['frs']}
    xset = {(c['fr'], c['dp']) for c in res['x']}
    out.append('| | ' + ' | '.join(cols) + ' |')
    out.append('|---|' + '---|' * len(cols))
    for fr in rows:
        marks = ['X' if own[fr] == dp or (fr, dp) in xset else '0' for dp in cols]
        out.append('| **%s** | %s |' % (fr, ' | '.join(marks)))
    out.append('')
    out.append('| FR | text | DP | text | parts |')
    out.append('|---|---|---|---|---|')
    dp_by_id = {d['id']: d for d in res['dps']}
    for fr in rows:
        f = next(f for f in res['frs'] if f['id'] == fr)
        d = dp_by_id.get(f['dp'])
        out.append('| %s | %s | %s | %s | %s |' % (fr, cell(f['text']), f['dp'] or '(none)', cell(d['text']) if d else '', cell('; '.join(d['parts'])) if d else ''))
    for dp in res['removal_candidates']:
        d = dp_by_id[dp]
        out.append('| (none) | | %s | %s | %s |' % (dp, cell(d['text']), cell('; '.join(d['parts']))))
    out.append('')
    if res['x']:
        out += ['Off-diagonal X (this skill\'s rule: changing the DP to tune its own FR forces a change to keep the FR met):', '',
                '| FR | DP | reason | evidence |', '|---|---|---|---|']
        for c in res['x']:
            out.append('| %s | %s | %s | %s |' % (c['fr'], c['dp'], cell(c['reason']), cell('; '.join(c['evidence']))))
        out.append('')
    notes = []
    if res['unmet_frs']:
        notes.append('FRs with no DP: %s.' % ', '.join(res['unmet_frs']))
    for dp in res['removal_candidates']:
        into = sorted((c['fr'] for c in res['x'] if c['dp'] == dp), key=natural)
        notes.append('DP %s serves no FR (removal candidate)%s.' % (dp, '; it still affects %s, so keep those FRs met if it goes' % ', '.join(into) if into else ''))
    for dp, v in res['dps_serving_several_frs'].items():
        notes.append('DP %s delivers several FRs (%s): coupled or integrated; check the X cells.' % (dp, ', '.join(v)))
    for part, v in res['parts_in_several_dps'].items():
        notes.append('Part %s sits in several DPs (%s): that is not coupling by itself.' % (part, ', '.join(v)))
    if notes:
        out += ['- ' + n for n in notes] + ['']
    return '\n'.join(out).rstrip() + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description='Check, classify and render one Axiomatic Design matrix (see the module docstring for the input format).')
    ap.add_argument('file', help='markdown or JSON table of FRs, DPs and X cells')
    ap.add_argument('--label', default='Design matrix', help='heading of the rendered block, e.g. "As found" or "Target"')
    ap.add_argument('--json', action='store_true', help='print the facts as JSON instead of markdown')
    ap.add_argument('--out', help='write the output here instead of stdout')
    args = ap.parse_args(argv)
    try:
        data = load(args.file)
    except (OSError, ValueError) as exc:
        sys.stderr.write('design_matrix: %s\n' % exc)
        log_run('design_matrix.py', 'render', 'refused', reason='unreadable input')
        return 1
    model, errors = validate(data)
    if errors:
        sys.stderr.write('design_matrix: %d problem(s) in %s\n' % (len(errors), args.file))
        for e in errors:
            sys.stderr.write('  - %s\n' % e)
        log_run('design_matrix.py', 'render', 'failed', errors=len(errors))
        return 1
    res = analyse(model, load_scc())
    text = json.dumps(res, indent=2, sort_keys=True) + '\n' if args.json else render(res, args.label)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    log_run('design_matrix.py', 'render', 'ok', frs=len(res['frs']), dps=len(res['dps']), x=len(res['x']), cls=res['class'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
