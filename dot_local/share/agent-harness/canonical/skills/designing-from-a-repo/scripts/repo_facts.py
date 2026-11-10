#!/usr/bin/env python3
"""Gather deterministic structural facts about a git repo at a pinned rev.

    repo_facts.py REPO [--rev REV] [--parts PARTS.tsv] [--scope GLOB ...]
                  [--since-days 120] [--max-commit-files 15] [--out facts.json]

Reads git only and never writes to REPO. The tree is read from `git archive`
at REV, so the working tree is ignored. Prints one JSON object (or writes
--out). Exit 0 on success; exit 2 with one stderr line on bad arguments, an
unknown rev or a path that is not a git repo.

Globs (--parts first column, --scope): `*` stays within one path segment, `**`
crosses `/` (`src/**` is all of src/; `src/**/x.ts` matches x.ts at any depth).
--scope adds a `scope` block for the matched files and replaces the top-level
edges and external_packages with counts; in_flight then holds counts only.
proof_commands lists gate, check and CI files plus test-like package.json scripts.
path_refs maps path strings in config and script files to the files or
directories they name.
"""
import argparse
import collections
import datetime
import itertools
import json
import os
import posixpath
import re
import subprocess
import sys
import tarfile
import tempfile

TS_EXTS = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')
PARSED_EXTS = TS_EXTS + ('.py',)
NONCODE_DIRS = {'fixtures', 'eval', 'vendor', 'node_modules', 'dist', 'build',
                'target', 'generated', '__snapshots__'}
LOCKFILES = {'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'Cargo.lock',
             'poetry.lock', 'Pipfile.lock', 'uv.lock', 'Gemfile.lock',
             'composer.lock', 'npm-shrinkwrap.json'}
GATE_RE = re.compile(r'boundar|dependency-cruiser|madge|import-linter|deptrac|'
                     r'archunit|\.eslintrc|eslint\.config|tach\.toml|\.importlinter', re.I)
GATE_FIRST_RE = re.compile(r'boundar|architecture|depcruise|dependency-cruiser|madge|'
                           r'import-linter|layers|deptrac|archunit', re.I)
DOC_RE = re.compile(r'(^|/)(PRD|REQUIREMENTS|CONTRACT|SPEC|ADR)[^/]*$|'
                    r'(^|/)docs/adr[^/]*/|(^|/)(AGENTS|CLAUDE|README)\.md$')
PLAN_RE = re.compile(r'\b(lane|step|phase|move|migrate|refactor|split)|\b(?-i:S[1-9])\b', re.I)
# Only real statements: import/export-from at line start, dynamic import(), require().
TS_IMPORT_RE = re.compile(
    r"""^\s*(?:import|export)\b[^;'"]*?\bfrom\s*['"]([^'"\n]+)['"]"""
    r"""|^\s*import\s*['"]([^'"\n]+)['"]"""
    r"""|\bimport\(\s*['"]([^'"\n]+)['"]\s*\)"""
    r"""|\brequire\(\s*['"]([^'"\n]+)['"]\s*\)""", re.M)
PY_FROM_RE = re.compile(r'^\s*from\s+(\.*)([\w.]*)\s+import\s+(.*)$', re.M)
PY_IMPORT_RE = re.compile(r'^\s*import\s+(.+)$', re.M)
COMMENT_START = ('/', '#', '*')
NOTES = {
    'lines': 'raw newline count, as wc -l; binary files count 0',
    'code_lines': 'non-blank lines minus comment-only lines (// and /* */ in JS/TS, # in Python); '
                  'other text files count non-blank lines',
    'cochange': 'with --scope, only commits touching a scope file count, and top_file_pairs lists '
                'only pairs with a scope file',
    'path_refs': 'tokens with a slash that name a tracked file or directory; ./ and ../ resolve from '
                 'the referring file; self and own-directory references are dropped',
}
PLAN_DAYS = 14
TOP = 20
PAIR_TOP = 30
EXAMPLES = 3
CAP = 50
SAMPLE = 20
HEADER_LINES = 20
HEADER_GATES = 3
PATH_REF_EXTS = ('.yaml', '.yml', '.sh', '.py', '.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs',
                 '.toml', '.json')
PATH_TOKEN_RE = re.compile(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+')
PROOF_RE = re.compile(r'gate|check|verify|test-all|(^|[-_.])ci([-_.]|$)', re.I)
SCRIPT_NAMES = {'test', 'check', 'lint', 'gate'}
PATH_EDGE_CAP = 200


def die(msg):
    sys.stderr.write(f'repo_facts: {msg}\n')
    sys.exit(2)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        die(message)


def parse_args(argv):
    p = _Parser(description='Structural facts about a git repo at a pinned rev.')
    p.add_argument('repo')
    p.add_argument('--rev', default='HEAD')
    p.add_argument('--parts', help='TSV lines: GLOB<TAB>PART NAME, first match wins. '
                                   '* stays in one path segment, ** crosses /')
    p.add_argument('--scope', nargs='+', metavar='GLOB', help='files to detail; glob rules as --parts')
    p.add_argument('--since-days', type=int, default=120)
    p.add_argument('--max-commit-files', type=int, default=15)
    p.add_argument('--out', help='write JSON here instead of stdout')
    a = p.parse_args(argv)
    if a.since_days < 0 or a.max_commit_files < 1:
        die('--since-days must be >= 0 and --max-commit-files must be >= 1')
    return a


def git(repo, *args):
    try:
        proc = subprocess.run(['git', '-C', repo, *args], capture_output=True,
                              encoding='utf-8', errors='replace')
    except OSError as exc:
        raise RuntimeError(str(exc))
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or f'git {args[0]} failed')
    return proc.stdout


def resolve(repo, rev):
    try:
        return git(repo, 'rev-parse', '--verify', '--quiet', rev + '^{commit}').strip() or None
    except RuntimeError:
        return None


def tok(s):
    parts = s.split()
    return parts[0] if parts else ''


def dir_key(path):
    d = posixpath.dirname(path)
    return '/'.join(d.split('/')[:2]) if d else '(root)'


def ext_of(path):
    return posixpath.splitext(path)[1] or '(none)'


def is_test(path):
    parts = path.split('/')
    name = parts[-1]
    return (any(s in name for s in ('.test.', '.spec.', '_test.'))
            or (name.startswith('test_') and name.endswith('.py'))
            or any(d in ('tests', '__tests__') for d in parts[:-1]))


def exclusion(path):
    """(tree path, reason) when the file is non-code, else None."""
    parts = path.split('/')
    for i, comp in enumerate(parts[:-1]):
        if comp in NONCODE_DIRS:
            return '/'.join(parts[:i + 1]), f'{comp} directory'
    if parts[-1] in LOCKFILES or parts[-1].endswith('.lock'):
        return path, 'lockfile'
    return None


def code_lines(text, py):
    """Non-blank lines that are not comment-only."""
    n, in_block = 0, False
    for line in text.splitlines():
        s = line.strip()
        if in_block:
            if '*/' not in s:
                continue
            in_block, s = False, s.split('*/', 1)[1].strip()
        elif not py and s.startswith('/*'):
            if '*/' not in s:
                in_block = True
                continue
            s = s.split('*/', 1)[1].strip()
        if s and not s.startswith('//') and not (py and s.startswith('#')):
            n += 1
    return n


def measure(path, data):
    """(raw lines as wc -l, code lines) for one blob. Binary blobs count 0."""
    if b'\0' in data:
        return 0, 0
    ext = posixpath.splitext(path)[1]
    if ext in PARSED_EXTS:
        return data.count(b'\n'), code_lines(data.decode('utf-8', 'replace'), ext == '.py')
    text = data.decode('utf-8', 'replace')
    return data.count(b'\n'), sum(1 for line in text.splitlines() if line.strip())


def tree_entries(repo, sha):
    """(path, mode, type, size) for every tracked entry at sha."""
    out = []
    for rec in git(repo, 'ls-tree', '-r', '-l', '-z', sha).split('\0'):
        if rec:
            meta, path = rec.split('\t', 1)
            mode, typ, _obj, size = meta.split()
            out.append((path, mode, typ, int(size) if size.isdigit() else 0))
    return out


def extract(repo, sha, tmp):
    tar_path = os.path.join(tmp, 'archive.tar')
    with open(tar_path, 'wb') as fh:
        proc = subprocess.run(['git', '-C', repo, 'archive', '--format=tar', sha],
                              stdout=fh, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError('git archive failed: ' + proc.stderr.decode('utf-8', 'replace').strip())
    tree = os.path.join(tmp, 'tree')
    os.mkdir(tree)
    with tarfile.open(tar_path) as tf:
        if hasattr(tarfile, 'data_filter'):
            tf.extractall(tree, filter='data')
        else:
            tf.extractall(tree)
    return tree


# --- import parsing -------------------------------------------------------

def norm(path):
    return '' if path in ('', '.') else posixpath.normpath(path)


def ancestors(path):
    d = posixpath.dirname(path)
    while True:
        yield d
        if not d:
            return
        d = posixpath.dirname(d)


def package_name(spec):
    parts = spec.split('/')
    return '/'.join(parts[:2]) if spec.startswith('@') else parts[0]


def resolve_ts(path, spec, files):
    base = norm(posixpath.join(posixpath.dirname(path), spec))
    stem, ext = posixpath.splitext(base)
    cands = [base]
    if ext in ('.js', '.jsx', '.mjs', '.cjs'):
        cands += [stem + e for e in ('.ts', '.tsx')]
    cands += [base + e for e in TS_EXTS]
    cands += [posixpath.join(base, 'index' + e) for e in TS_EXTS]
    return next((c for c in cands if c in files), None)


def py_candidates(base):
    return [base + '.py', posixpath.join(base, '__init__.py')] if base else ['__init__.py']


def resolve_py(path, level, module, files):
    if level:
        root = posixpath.dirname(path)
        for _ in range(level - 1):
            root = posixpath.dirname(root)
        roots = [root]
    else:
        roots = list(ancestors(path))
    rel = module.replace('.', '/')
    for root in roots:
        base = norm(posixpath.join(root, rel)) if rel else norm(root)
        hit = next((c for c in py_candidates(base) if c in files), None)
        if hit:
            return hit
    return None


def py_imports(text):
    """Yield (level, module, names) for each import statement."""
    for m in PY_FROM_RE.finditer(text):
        names = [tok(n.split(' as ')[0]) for n in m.group(3).strip().strip('()').split(',')]
        yield len(m.group(1)), m.group(2), [n for n in names if n and n != '*']
    for m in PY_IMPORT_RE.finditer(text):
        for item in m.group(1).split(','):
            mod = tok(item.split(' as ')[0])
            if mod:
                yield 0, mod, []


def scan_imports(files, texts):
    """Return (internal file edges, external packages per dir, external import count in test files)."""
    edges = set()
    external = collections.defaultdict(collections.Counter)
    test_ext = 0
    for path in sorted(texts):
        text = texts[path]
        test = files[path]['test']
        if path.endswith('.py'):
            for level, mod, names in py_imports(text):
                hits = set()
                for target in [mod] + [f'{mod}.{n}' if mod else n for n in names]:
                    t = resolve_py(path, level, target, files) if target else None
                    if t:
                        hits.add(t)
                edges |= {(path, t) for t in hits if t != path}
                if level == 0 and mod and not hits:
                    if test:
                        test_ext += 1
                    else:
                        external[dir_key(path)][mod.split('.')[0]] += 1
            continue
        for m in TS_IMPORT_RE.finditer(text):
            spec = next(g for g in m.groups() if g)
            if spec.startswith('.'):
                t = resolve_ts(path, spec, files)
                if t and t != path:
                    edges.add((path, t))
            elif not spec.startswith('/'):
                if test:
                    test_ext += 1
                else:
                    external[dir_key(path)][package_name(spec)] += 1
    return edges, external, test_ext


# --- graph and table helpers ----------------------------------------------

def sccs(nodes, adj):
    """Strongly connected components of size > 1 (iterative Tarjan)."""
    index, low, on_stack, stack, out = {}, {}, set(), [], []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(adj.get(root, ())))]
        while work:
            node, it = work[-1]
            descended = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(adj.get(w, ()))))
                    descended = True
                    break
                if w in on_stack:
                    low[node] = min(low[node], index[w])
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp))
    return out


def scc_components(nodes, pairs):
    """Cycle components (full member lists), largest first."""
    adj = collections.defaultdict(list)
    for a, b in pairs:
        adj[a].append(b)
    return sorted(sccs(sorted(nodes), adj), key=lambda c: (-len(c), c[0]))


def cycle_rows(comps):
    return [{'size': len(c), 'members': c[:CAP], 'truncated': len(c) > CAP} for c in comps]


def dir_sizes(files):
    out = {}
    for path, info in files.items():
        rec = out.setdefault(dir_key(path), {'files': 0, 'code_lines': 0, 'test_lines': 0})
        rec['files'] += 1
        key = 'test_lines' if info['test'] else 'code_lines'
        rec[key] += info['code_lines']
    return dict(sorted(out.items()))


def group_edges(edges, key):
    """Count cross-group edges, where key(file) names the group (None = unmapped)."""
    groups = collections.defaultdict(list)
    for a, b in sorted(edges):
        ka, kb = key(a), key(b)
        if ka and kb and ka != kb:
            groups[(ka, kb)].append([a, b])
    rows = [{'from': x, 'to': y, 'count': len(v), 'examples': v[:EXAMPLES]}
            for (x, y), v in groups.items()]
    rows.sort(key=lambda r: (-r['count'], r['from'], r['to']))
    return rows


def top_pairs(counter):
    rows = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:PAIR_TOP]
    return [{'a': a, 'b': b, 'commits': n} for (a, b), n in rows]


# --- git-derived facts ----------------------------------------------------

def cochange(repo, sha, present, days, max_files, chosen):
    out = git(repo, '-c', 'core.quotepath=off', 'log', f'--since={days}.days.ago',
              '--name-only', '--format=@@%H', sha)
    commits = []
    for line in out.splitlines():
        if line.startswith('@@'):
            commits.append([])
        elif line.strip() and commits:
            commits[-1].append(line)
    used = skipped = 0
    pairs = collections.Counter()
    dpairs = collections.Counter()
    for paths in commits:
        if chosen is not None and not chosen.intersection(paths):
            continue
        if len(paths) > max_files:
            skipped += 1
            continue
        used += 1
        kept = sorted({p for p in paths if p in present})
        pairs.update(c for c in itertools.combinations(kept, 2) if chosen is None or chosen.intersection(c))
        dpairs.update(itertools.combinations(sorted({dir_key(p) for p in kept}), 2))
    return {'window_days': days, 'commits_used': used, 'commits_skipped': skipped,
            'top_file_pairs': top_pairs(pairs), 'top_dir_pairs': top_pairs(dpairs)}


def worktrees(repo):
    out = []
    for block in git(repo, 'worktree', 'list', '--porcelain').strip().split('\n\n'):
        rec = dict(line.partition(' ')[::2] for line in block.splitlines())
        out.append({'path': rec.get('worktree'), 'head': rec.get('HEAD'),
                    'branch': rec.get('branch', '').replace('refs/heads/', '') or None,
                    'detached': 'detached' in rec})
    return out


def in_flight(repo, sha):
    refs = git(repo, 'for-each-ref', f'--no-merged={sha}',
               '--format=%(refname)%09%(committerdate:iso-strict)', 'refs/heads', 'refs/remotes')
    branches = []
    for line in refs.splitlines():
        ref, _, date = line.partition('\t')
        if ref and not ref.endswith('/HEAD'):
            branches.append({'ref': ref, 'last_commit': date})
    plan = []
    for line in git(repo, 'log', f'--since={PLAN_DAYS}.days.ago', '--format=%H%x09%cI%x09%s', sha).splitlines():
        fields = line.split('\t', 2)
        if len(fields) == 3 and PLAN_RE.search(fields[2]):
            plan.append({'commit': fields[0], 'date': fields[1], 'subject': fields[2]})
    return {'branches_not_merged_into_rev': branches, 'worktrees': worktrees(repo),
            'plan_commits_14d': plan}


def scope_branches(repo, sha, specs, wts):
    """Local and remote branches, plus detached worktree heads, whose diff from rev touches scope."""
    fmt = '--format=%(refname)%09%(objectname)%09%(committerdate:iso-strict)'
    refs = [line.split('\t') for line in git(repo, 'for-each-ref', fmt, 'refs/heads', 'refs/remotes').splitlines()]
    cands = [tuple(r) for r in refs if not r[0].endswith('/HEAD')]
    for wt in wts:
        if wt['head'] and not wt['branch']:
            date = git(repo, 'log', '-1', '--format=%cI', wt['head']).strip()
            cands.append((f"worktree:{wt['path']}", wt['head'], date))
    rows = []
    for ref, obj, date in sorted(cands):
        rng = f'{sha}...{obj}'
        try:
            changed = git(repo, '-c', 'core.quotepath=off', 'diff', '--name-only', rng,
                          '--', *specs).splitlines()
        except RuntimeError as exc:
            rows.append({'ref': ref, 'last_commit': date, 'error': str(exc)})
            continue
        if changed:
            behind, ahead = git(repo, 'rev-list', '--left-right', '--count', rng).split()
            rows.append({'ref': ref, 'last_commit': date, 'ahead': int(ahead), 'behind': int(behind),
                         'files_changed': len(changed), 'files': changed[:SAMPLE]})
    return rows


def plan_touching(repo, specs, plan):
    rows = []
    for c in plan:
        changed = git(repo, 'diff-tree', '--no-commit-id', '--name-only', '-r', '--root',
                      c['commit'], '--', *specs).splitlines()
        if changed:
            rows.append({**c, 'files_changed': len(changed), 'files': changed[:SAMPLE]})
    return rows


def matching(files, globs):
    rules = [glob_re(g) for g in globs]
    return sorted(p for p in files if any(rx.match(p) for rx in rules))


def in_scope(node, chosen):
    """True for a scope file, or for a directory ('x/') that contains one."""
    return node in chosen or (node.endswith('/') and any(p.startswith(node) for p in chosen))


def scope_report(repo, sha, globs, files, edges, texts, comps, flight):
    specs = [':(glob)' + g for g in globs]
    picked = matching(files, globs)
    chosen = set(picked)
    adj = collections.defaultdict(set)
    imports = collections.defaultdict(list)
    importers = collections.defaultdict(list)
    for a, b in edges:
        adj[a].add(b)
        if a in chosen:
            imports[a].append(b)
        if b in chosen:
            importers[b].append(a)
    tests = []
    for path in sorted(p for p in files if files[p]['test']):
        text = texts.get(path, '')
        named = {s for s in picked if re.search(re.escape(posixpath.splitext(s)[0]) + r'(?![\w-])', text)}
        if named | (adj[path] & chosen):
            tests.append({'file': path, 'scope_files': sorted(named | (adj[path] & chosen))})
    return {
        'globs': globs,
        'files': [{'file': p, 'lines': files[p]['lines'], 'code_lines': files[p]['code_lines'],
                   'imports': sorted(imports[p]), 'importers': sorted(importers[p])}
                  for p in picked],
        'tests': tests,
        'cycles': cycle_rows([c for c in comps if chosen & set(c)]),
        'branches_touching_scope': scope_branches(repo, sha, specs, flight['worktrees']),
        'plan_commits_touching_scope': plan_touching(repo, specs, flight['plan_commits_14d']),
    }


# --- gates and docs ------------------------------------------------------

def header(text):
    """The leading comment block (at most HEADER_LINES), else the first HEADER_LINES lines."""
    lines = text.splitlines()
    i = next((i for i, line in enumerate(lines) if line.strip()), 0)
    if lines[i:i + 1] and lines[i].lstrip()[:1] in COMMENT_START:
        end = i
        while end < len(lines) and end - i < HEADER_LINES and lines[end].lstrip()[:1] in COMMENT_START:
            end += 1
        return '\n'.join(lines[i:end])
    return '\n'.join(lines[:HEADER_LINES])


def gates(tree, paths):
    ranked = sorted(paths, key=lambda p: (not GATE_FIRST_RE.search(posixpath.basename(p)), p))
    out = []
    for i, p in enumerate(ranked):
        rec = {'file': p}
        if i < HEADER_GATES:
            with open(os.path.join(tree, p), 'rb') as fh:
                rec['header'] = header(fh.read().decode('utf-8', 'replace'))
        out.append(rec)
    return out


# --- parts ----------------------------------------------------------------

def glob_re(glob):
    out, i = [], 0
    while i < len(glob):
        if glob.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
            continue
        if glob.startswith('**', i):
            out.append('.*')
            i += 2
            continue
        c = glob[i]
        out.append('[^/]*' if c == '*' else '[^/]' if c == '?' else re.escape(c))
        i += 1
    return re.compile('^' + ''.join(out) + '$')


def read_parts(path):
    try:
        with open(path, encoding='utf-8') as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        die(f'cannot read --parts: {exc.strerror}')
    rules = []
    for n, line in enumerate(lines, 1):
        if not line.strip() or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 2 or not fields[0] or not fields[1]:
            die(f'bad --parts line {n}: want GLOB<TAB>PART NAME')
        rules.append((glob_re(fields[0]), fields[1]))
    return rules


def parts_report(rules, files, edges):
    by_part = {name: {'files': 0, 'code_lines': 0, 'test_lines': 0} for _rx, name in rules}
    part_of, unmapped = {}, []
    for path in sorted(files):
        name = next((n for rx, n in rules if rx.match(path)), None)
        if name is None:
            unmapped.append(path)
            continue
        part_of[path] = name
        rec = by_part[name]
        rec['files'] += 1
        key = 'test_lines' if files[path]['test'] else 'code_lines'
        rec[key] += files[path]['code_lines']
    return {'by_part': by_part, 'edges': group_edges(edges, part_of.get),
            'unmapped': {'count': len(unmapped), 'samples': unmapped[:SAMPLE]}}


# --- proof commands and path references ----------------------------------

def proof_commands(files, tree):
    out = []
    for p in sorted(files):
        base = posixpath.basename(p)
        if (PROOF_RE.search(base) or base in ('Makefile', 'justfile') or base.startswith('Taskfile')
                or p.startswith('.github/workflows/')):
            out.append({'file': p})
        if base == 'package.json':
            try:
                with open(os.path.join(tree, p), 'rb') as fh:
                    scripts = json.loads(fh.read().decode('utf-8', 'replace')).get('scripts')
            except (ValueError, AttributeError):
                continue
            if isinstance(scripts, dict):
                out += [{'file': p, 'script': n, 'command': str(scripts[n])}
                        for n in sorted(scripts) if n in SCRIPT_NAMES]
    return out


def is_ref_source(path):
    return posixpath.basename(path) == 'Makefile' or posixpath.splitext(path)[1] in PATH_REF_EXTS


def dir_set(names):
    dirs = set()
    for p in names:
        d = posixpath.dirname(p)
        while d and d not in dirs:
            dirs.add(d)
            d = posixpath.dirname(d)
    return dirs


def ref_target(src, token, tracked, dirs):
    """A tracked file, or 'dir/' for a tracked directory, named by token; else None."""
    p = norm(posixpath.join(posixpath.dirname(src), token) if token.startswith(('./', '../')) else token)
    if p in tracked:
        return p
    return p + '/' if p and p in dirs else None


def path_ref_counts(ref_texts, tracked, dirs):
    counts = collections.Counter()
    for src, text in ref_texts.items():
        for raw in PATH_TOKEN_RE.findall(text):
            tgt = ref_target(src, raw.rstrip('.'), tracked, dirs)
            if tgt and tgt != src and tgt != posixpath.dirname(src) + '/':
                counts[(src, tgt)] += 1
    return counts


def depth2(node):
    """Two-level directory key of a file or of a 'dir/' target."""
    return '/'.join(node.rstrip('/').split('/')[:2]) if node.endswith('/') else dir_key(node)


def path_ref_report(counts, chosen):
    if chosen is not None:
        counts = {k: v for k, v in counts.items() if in_scope(k[0], chosen) or in_scope(k[1], chosen)}
    pairs = set(counts)
    dirs = group_edges(pairs, depth2)
    dpairs = {(depth2(s), depth2(t)) for s, t in pairs if depth2(s) != depth2(t)}
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        'edge_count': len(counts),
        'edge_cap': PATH_EDGE_CAP,
        'edges': [{'from': s, 'to': t, 'count': n} for (s, t), n in rows[:PATH_EDGE_CAP]],
        'dir_pair_count': len(dirs),
        'dir_pairs': dirs[:PAIR_TOP],
        'cycles': cycle_rows(scc_components({x for pr in dpairs for x in pr}, dpairs)),
    }


# --- driver ---------------------------------------------------------------

def analyse(repo, sha, args, rules, tmp):
    entries = tree_entries(repo, sha)
    names = {path: size for path, _mode, _typ, size in entries}
    skipped = collections.Counter()
    blobs = []
    for path, mode, typ, size in entries:
        if typ != 'blob':
            skipped['submodule'] += 1
        elif mode == '120000':
            skipped['symlink'] += 1
        else:
            blobs.append(path)
    excluded, candidates = {}, []
    for path in blobs:
        ex = exclusion(path)
        if ex is None:
            candidates.append(path)
        else:
            rec = excluded.setdefault(ex[0], {'reason': ex[1], 'files': 0})
            rec['files'] += 1
    tree = extract(repo, sha, tmp)
    files, texts, ref_texts = {}, {}, {}
    for path in candidates:
        try:
            with open(os.path.join(tree, path), 'rb') as fh:
                data = fh.read()
        except FileNotFoundError:
            skipped['missing_from_archive'] += 1
            continue
        except OSError:
            skipped['unreadable'] += 1
            continue
        raw, code = measure(path, data)
        files[path] = {'lines': raw, 'code_lines': code, 'test': is_test(path)}
        if posixpath.splitext(path)[1] in PARSED_EXTS:
            texts[path] = data.decode('utf-8', 'replace')
        if is_ref_source(path):
            ref_texts[path] = data.decode('utf-8', 'replace')

    chosen = set(matching(files, args.scope)) if args.scope else None
    edges, external, test_ext = scan_imports(files, texts)
    dirs = group_edges(edges, dir_key)
    languages = collections.Counter(ext_of(p) for p in files)
    importers = collections.Counter(b for _a, b in edges)
    file_comps = scc_components(set(files), edges)
    dir_comps = scc_components({dir_key(p) for p in files}, [(r['from'], r['to']) for r in dirs])
    flight = in_flight(repo, sha)
    out = {
        'notes': NOTES,
        'languages': dict(sorted(languages.items())),
        'parsed': sorted(e for e in languages if e in PARSED_EXTS),
        'unparsed': sorted(e for e in languages if e not in PARSED_EXTS),
        'excluded': dict(sorted(excluded.items())),
        'sizes': dir_sizes(files),
        'external_test_imports': test_ext,
        'dir_edges': dirs,
        'cycles': {'dir': cycle_rows(dir_comps), 'file': cycle_rows(file_comps)},
        'fan_in': [{'file': f, 'importers': n} for f, n in
                   sorted(importers.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]],
        'top_files_by_size': [{'file': p, 'lines': files[p]['lines'], 'code_lines': files[p]['code_lines']}
                              for p in sorted(files, key=lambda p: (-files[p]['lines'], p))[:TOP]],
        'cochange': cochange(repo, sha, set(names), args.since_days, args.max_commit_files, chosen),
        'proof_commands': proof_commands(files, tree),
        'path_refs': path_ref_report(path_ref_counts(ref_texts, set(names), dir_set(names)), chosen),
        'gates': gates(tree, [p for p in files if GATE_RE.search(p)]),
        'docs_found': [{'path': p, 'bytes': names[p]} for p in sorted(files) if DOC_RE.search(p)],
        'skipped': {'count': sum(skipped.values()), 'by_reason': dict(sorted(skipped.items()))},
    }
    if args.scope:
        out['edge_count'] = len(edges)
        out['external_package_count'] = len({pkg for c in external.values() for pkg in c})
        out['in_flight'] = {k: len(v) for k, v in flight.items()}
        out['scope'] = scope_report(repo, sha, args.scope, files, edges, texts, file_comps, flight)
    else:
        out['edges'] = [list(e) for e in sorted(edges)]
        out['external_packages'] = {d: dict(sorted(c.items())) for d, c in sorted(external.items())}
        out['in_flight'] = flight
    if rules is not None:
        out['parts'] = parts_report(rules, files, edges)
    return out


def main(argv=None):
    args = parse_args(argv)
    try:
        repo = git(args.repo, 'rev-parse', '--show-toplevel').strip()
    except RuntimeError:
        die(f'not a git repo: {args.repo}')
    sha = resolve(repo, args.rev) or die(f'unknown rev: {args.rev}')
    rules = read_parts(args.parts) if args.parts else None
    try:
        with tempfile.TemporaryDirectory(prefix='repo_facts-') as tmp:
            body = analyse(repo, sha, args, rules, tmp)
    except RuntimeError as exc:
        die(str(exc))
    facts = {
        'rev_arg': args.rev,
        'rev': sha,
        'head_start': sha,
        'head_end': resolve(repo, args.rev),
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    }
    facts.update(body)
    text = json.dumps(facts, indent=2) + '\n'
    if args.out:
        try:
            with open(args.out, 'w', encoding='utf-8') as fh:
                fh.write(text)
        except OSError as exc:
            die(f'cannot write --out: {exc.strerror}')
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
