"""Rust edges for repo_facts.py: module declarations, `use` and path references, and Cargo dependencies between workspace crates.

Imported by repo_facts.py, never run. Stdlib only. Everything is read from text: nothing is compiled.

    scan(files, texts) -> (edges, mod_edges, externals)

`texts` maps a tracked path to its text for every `.rs` file and every `Cargo.toml`. `files` is the tracked set (a dict or set of paths).
edges are (from file, to file) pairs and include mod_edges. externals is a list of (file, crate name) for each `use` of a crate that is
neither in the workspace nor std, core or alloc (a name that starts with a capital is a type or enum, not a crate).

What makes an edge, from the file that writes it to the file it reaches:
* `mod x;` in a file: to the file that holds x (x.rs or x/mod.rs beside it, or the `#[path = "..."]` file). A `mod x { ... }` written
  inline makes no edge (same file), but it is tracked so `self::` and `super::` start from the right module.
* `use crate::a::b`, `use super::a`, `use self::a`, `use <workspace crate>::a`, and the same paths written inline in code
  (`crate::a::f()`): to the file of the deepest module the path names. An item at the end of the path (a fn or struct) is not a module, so
  the path stops at the module before it. A path that names only the crate root reaches the root file (lib.rs or main.rs), which also holds
  what that file re-exports; this script does not follow a re-export to the file that defines it.
* In a Cargo.toml: each `path = "..."` dependency, and each `workspace = true` dependency the workspace root gives a path, in
  [dependencies], [dev-dependencies], [build-dependencies] and their [target.*] forms: from this Cargo.toml to the one it names.
Comments and string contents are blanked before reading, so a `use` in a doc example or a test fixture string makes no edge.
Not followed: macro-generated modules, `include!`, a `use` that names a module only through a re-export, a crate renamed in Cargo.toml
(`package = "x"`), and a module reached only through `#[path]` inside an inline module.
"""
import bisect
import posixpath
import re

ROOT_NAMES = ('lib.rs', 'main.rs', 'build.rs')
ROOT_DIRS = ('bin', 'tests', 'examples', 'benches')
SKIP_EXTERNAL = {'std', 'core', 'alloc', 'crate', 'self', 'super', 'Self'}
DEP_TABLES = ('dependencies', 'dev-dependencies', 'build-dependencies')
EVENT_RE = re.compile(r'\bmod\s+(\w+)\s*([;{])|(\{)|(\})')
PATH_MOD_RE = re.compile(r'#\[\s*path\s*=\s*"( *)"\s*\]\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;')
USE_RE = re.compile(r'(?<![\w:])use\s+([^;]+);')
INLINE_RE = re.compile(r'(?<![\w:.])(crate|super|self|[A-Za-z_]\w*)((?:\s*::\s*[A-Za-z_]\w*)+)')
TOKEN_RE = re.compile(r'::|[{},*]|[A-Za-z_]\w*')
RAW_STR_RE = re.compile(r'b?r(#*)"')
CHAR_RE = re.compile(r"'(?:\\[^']*|[^\\'\n])'")


def blank(text):
    """text with comments and the insides of string and char literals turned to spaces (newlines and offsets kept)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == '//':
            j = text.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif two == '/*':
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith('/*', j):
                    depth, j = depth + 1, j + 2
                elif text.startswith('*/', j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            out.append(re.sub(r'[^\n]', ' ', text[i:j]))
            i = j
        elif c in 'rb' and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == '_')) and RAW_STR_RE.match(text, i):
            m = RAW_STR_RE.match(text, i)
            end = text.find('"' + m.group(1), m.end())
            end = n if end < 0 else end + 1 + len(m.group(1))
            out.append(text[i:m.end()] + re.sub(r'[^\n]', ' ', text[m.end():end - 1 - len(m.group(1))]) + text[end - 1 - len(m.group(1)):end])
            i = end
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == '\\' else 1
            j = min(j, n)
            out.append('"' + re.sub(r'[^\n]', ' ', text[i + 1:j]) + ('"' if j < n else ''))
            i = j + 1
        elif c == "'" and CHAR_RE.match(text, i):
            m = CHAR_RE.match(text, i)
            out.append("'" + ' ' * (m.end() - i - 2) + "'")
            i = m.end()
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def expand(spec):
    """The paths a `use` tree names, each a list of segments: `a::{b, c::d as e, self, f::*}` is [a b] [a c d] [a] [a f]."""
    toks = TOKEN_RE.findall(spec)
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def tree(prefix):
        nonlocal pos
        path = list(prefix)
        while True:
            t = peek()
            if t == '::':
                pos += 1
            elif t == '{':
                pos += 1
                found = []
                while peek() not in ('}', None):
                    found += tree(path)
                    if peek() == ',':
                        pos += 1
                pos += 1
                return found
            elif t == '*':
                pos += 1
                return [path]
            elif t and re.match(r'[A-Za-z_]', t):
                pos += 1
                if t == 'as':
                    pos += 1  # the alias
                    return [path]
                path.append(t)
            else:
                return [path]
            if peek() in (',', '}', None):
                return [path]

    out = tree([])
    cleaned = []
    for p in out:
        if p and p[-1] == 'self' and len(p) > 1:
            p = p[:-1]
        cleaned.append(p)
    return [p for p in cleaned if p]


def package_name(manifest):
    return (manifest.get('package') or {}).get('name')


def parse_manifests(files, texts):
    """{manifest path: parsed dict} for every readable Cargo.toml. tomllib (Python 3.11) is imported here, so a repo with no Cargo.toml runs on an older Python."""
    out = {}
    for path in sorted(texts):
        if posixpath.basename(path) == 'Cargo.toml':
            try:
                import tomllib
            except ImportError:
                raise RuntimeError('reading Cargo.toml needs Python 3.11 or later (tomllib)')
            try:
                out[path] = tomllib.loads(texts[path])
            except (tomllib.TOMLDecodeError, ValueError):
                continue
    return out


def crate_roots(manifests, rs_files):
    """{root file: package dir}, and {crate ident: lib root file}. A root is a crate's top file: lib.rs, main.rs, build.rs, a [lib] or
    [[bin]] path, a src/bin, tests, examples or benches file of a package."""
    roots, libs = {}, {}
    for mpath, man in manifests.items():
        if 'package' not in man:
            continue
        pdir = posixpath.dirname(mpath)
        rel = lambda p: posixpath.normpath(posixpath.join(pdir, p))
        name = package_name(man)
        lib = man.get('lib') or {}
        lib_path = rel(lib.get('path', 'src/lib.rs'))
        if lib_path in rs_files:
            roots[lib_path] = pdir
            libs[(lib.get('name') or name or '').replace('-', '_')] = lib_path
        for b in man.get('bin') or []:
            if b.get('path') and rel(b['path']) in rs_files:
                roots[rel(b['path'])] = pdir
        for t in (man.get('test') or []) + (man.get('example') or []) + (man.get('bench') or []):
            if t.get('path') and rel(t['path']) in rs_files:
                roots[rel(t['path'])] = pdir
        src = posixpath.join(pdir, 'src')
        folders = {posixpath.join(src, 'bin') if d == 'bin' else posixpath.join(pdir, d) for d in ROOT_DIRS}
        for f in rs_files:
            here = posixpath.dirname(f)
            if (here == src and posixpath.basename(f) in ROOT_NAMES) or (here == pdir and posixpath.basename(f) == 'build.rs') or here in folders:
                roots.setdefault(f, pdir)
    libs.pop('', None)
    return roots, libs


def find_events(bl):
    """(mod declarations [(pos, name, inline?)], inline mod blocks [(open pos, close pos, names)])."""
    decls, blocks, stack = [], [], []
    for m in EVENT_RE.finditer(bl):
        if m.group(1):
            if m.group(2) == ';':
                decls.append((m.start(), m.group(1), False))
            else:
                decls.append((m.start(), m.group(1), True))
                stack.append((m.end() - 1, m.group(1)))
        elif m.group(3):
            stack.append((m.start(), None))
        else:
            if stack:
                start, name = stack.pop()
                if name:
                    blocks.append((start, m.start(), name))
    return decls, blocks


def inline_path(blocks, pos):
    """Names of the inline `mod x { }` blocks that hold pos, outermost first."""
    inside = sorted((b for b in blocks if b[0] < pos < b[1]), key=lambda b: b[0])
    return tuple(b[2] for b in inside)


def child_dir(path, is_root):
    return posixpath.dirname(path) if is_root or posixpath.basename(path) == 'mod.rs' else posixpath.splitext(path)[0]


def build_modules(rs_files, roots, blanked, originals):
    """({(root, module path): file}, {file: [(root, module path)]}, mod edges, inline blocks per file).
    A file that several crate roots declare (tests/common/mod.rs) has one context for each."""
    modmap, owner, mod_edges, blocks_of = {}, {}, set(), {}
    queue, seen = [], set()
    for root in sorted(roots):
        modmap[(root, ())] = root
        owner.setdefault(root, []).append((root, ()))
        queue.append((root, root, ()))
        seen.add((root, root))
    while queue:
        f, root, mp = queue.pop(0)
        if f not in blocks_of:
            blocks_of[f] = find_events(blanked[f])[1]
        decls, blocks = find_events(blanked[f])
        paths = {m.group(2): originals[f][m.start(1):m.end(1)] for m in PATH_MOD_RE.finditer(blanked[f])}
        base = child_dir(f, f in roots)
        for pos, name, inline in decls:
            q = inline_path(blocks, pos)
            if inline:
                modmap.setdefault((root, mp + q + (name,)), f)
                continue
            if name in paths and not q:
                cands = [posixpath.normpath(posixpath.join(posixpath.dirname(f), paths[name]))]
            else:
                d = posixpath.join(base, *q) if q else base
                cands = [posixpath.join(d, name + '.rs'), posixpath.join(d, name, 'mod.rs')]
            hit = next((c for c in cands if c in rs_files), None)
            if not hit:
                continue
            modmap[(root, mp + q + (name,))] = hit
            if hit != f:
                mod_edges.add((f, hit))
            if (hit, root) not in seen:
                seen.add((hit, root))
                owner.setdefault(hit, []).append((root, mp + q + (name,)))
                queue.append((hit, root, mp + q + (name,)))
    return modmap, owner, mod_edges, blocks_of


def walk(modmap, root, start, segs):
    """The file of the deepest module that segs names, starting at module path `start` of crate `root`; None if start is no module."""
    cur = tuple(start)
    if (root, cur) not in modmap:
        return None
    for s in segs:
        if (root, cur + (s,)) in modmap:
            cur += (s,)
        else:
            break
    return modmap[(root, cur)]


def resolve(segs, root, mp, modmap, libs):
    """The file a path reaches from module `mp` of crate `root`, or None (an external crate or an unknown path)."""
    first, rest = segs[0], segs[1:]
    if first == 'crate':
        return walk(modmap, root, (), rest)
    if first == 'self':
        return walk(modmap, root, mp, rest)
    if first == 'super':
        depth, i = 0, 0
        while i < len(segs) and segs[i] == 'super':
            depth, i = depth + 1, i + 1
        if depth > len(mp):
            return None
        return walk(modmap, root, mp[:len(mp) - depth], segs[i:])
    if (root, mp + (first,)) in modmap:
        return walk(modmap, root, mp, segs)
    if first in libs:
        return walk(modmap, libs[first], (), rest)
    return None


def cargo_edges(manifests, files):
    edges = set()
    ws_deps = {}
    for mpath, man in manifests.items():
        ws = man.get('workspace')
        if ws:
            ws_deps[posixpath.dirname(mpath)] = ws.get('dependencies') or {}

    def workspace_root(mdir):
        d = mdir
        while True:
            if d in ws_deps:
                return d
            if not d:
                return None
            d = posixpath.dirname(d)

    for mpath, man in manifests.items():
        mdir = posixpath.dirname(mpath)
        tables = [man.get(t) or {} for t in DEP_TABLES]
        for tgt in (man.get('target') or {}).values():
            tables += [tgt.get(t) or {} for t in DEP_TABLES]
        for table in tables:
            for name, spec in table.items():
                if not isinstance(spec, dict):
                    continue
                path, base = spec.get('path'), mdir
                if spec.get('workspace'):
                    wroot = workspace_root(mdir)
                    given = ws_deps.get(wroot, {}).get(name) if wroot is not None else None
                    path, base = (given or {}).get('path') if isinstance(given, dict) else None, wroot
                if path:
                    target = posixpath.join(posixpath.normpath(posixpath.join(base, path)), 'Cargo.toml')
                    if target in files and target != mpath:
                        edges.add((mpath, target))
    return edges


def scan(files, texts):
    rs = {p for p in texts if p.endswith('.rs')}
    manifests = parse_manifests(files, texts)
    roots, libs = crate_roots(manifests, rs)
    blanked = {p: blank(texts[p]) for p in rs}
    modmap, owner, mod_edges, blocks_of = build_modules(rs, roots, blanked, texts)
    edges = set(mod_edges) | cargo_edges(manifests, files)
    externals = set()
    for f in sorted(rs):
        bl = blanked[f]
        blocks = blocks_of.get(f, [])
        spans = [m.span() for m in USE_RE.finditer(bl)]
        masked = list(bl)
        for a, b in spans:
            masked[a:b] = [' '] * (b - a)
        masked = ''.join(masked)
        for ctx in owner.get(f) or [None]:
            def reach(segs, pos):
                if ctx:
                    return resolve(segs, ctx[0], ctx[1] + inline_path(blocks, pos), modmap, libs)
                return resolve(segs, None, (), modmap, libs) if segs[0] in libs else None
            for m in USE_RE.finditer(bl):
                for segs in expand(m.group(1)):
                    target = reach(segs, m.start())
                    if target:
                        if target != f:
                            edges.add((f, target))
                    elif segs[0] not in SKIP_EXTERNAL and segs[0] not in libs and not segs[0][:1].isupper():  # `use Kind::*` names an enum, not a crate
                        externals.add((f, segs[0], m.start()))
            for m in INLINE_RE.finditer(masked):
                segs = [m.group(1)] + re.findall(r'[A-Za-z_]\w*', m.group(2))
                if segs[0] in ('crate', 'super', 'self') or segs[0] in libs:
                    target = reach(segs, m.start())
                    if target and target != f:
                        edges.add((f, target))
    return edges, set(mod_edges), sorted((f, name) for f, name, _pos in externals)
