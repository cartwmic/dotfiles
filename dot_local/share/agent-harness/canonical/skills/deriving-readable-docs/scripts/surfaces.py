#!/usr/bin/env python3
"""List the surfaces of any repo: where a user or a caller meets it. Reads files only; no repo code is run.

usage: surfaces.py <repo> [--json]
       surfaces.py <repo> --resolve names.txt

Prints one row per surface, `kind | name | path:line`, grouped by kind. Every row is a literal line of the repo (checked by
the tests), so it is a safe `path:line` to cite. Kinds: entry, command, flag, route, event, env, config, manifest, export, doc, ci.
  Python   [project.scripts], __main__.py, `if __name__ == "__main__"`, add_argument, click options, route decorators, os.environ / getenv
  Go       `package main`, cobra `Use:`, flag.X and Flags().X, urfave/cli Name:, Handle and HandleFunc, regexp route tables (`^/...`), os.Getenv
  JS, TS   package.json bin, main, exports and every script; .command(, .option(, app.get( and router.use(, socket.on(, process.env.X;
           in a file that reads argv (process.argv, parseArgs, yargs, commander): a default `program = 'name'`, a `usage: name` string, `case 'cmd':` arms,
           `command === 'cmd'` tests and the option names of a parseArgs table, as --name
  Rust     [[bin]], fn main in src/main.rs and src/bin/, clap #[arg(...)] with its field name, #[command(...)], attribute routes (#[get("/x")] of actix and rocket), env::var, pub items of lib.rs
  Shell    a #! file, the -x|--long) arms of a case, ${VAR:-default} and export VAR=
  Any      Dockerfile ENTRYPOINT and CMD, compose services, Makefile and Taskfile targets, CI `run:` steps,
           *.toml *.yml *.yaml *.ini *.conf *.cfg and *.example files at most two folders deep, README and docs/
It is a reading aid and a completeness check, not the truth. It misses what a regex cannot see: enum or table command registries,
a hand-parsed argv, a third-party args module, UI code. A scout reads the README and names those; --resolve checks each name.

--json prints the rows as a JSON array of {kind, name, file, line}.
--resolve names.txt reads one name a line (the name as it appears in the code; # starts a comment) and prints `name | path:line` for the product: a file
that is not a test, a fixture, a script (a `scripts/` folder) or a doc. Order: the surface row the scan above found with that exact name (a command before a
route, a flag, an event; the shallowest file first, so `src/reach/cli.ts` beats `src/reach/usecases/x/send.ts`), else the line that defines it (function,
class, def, const, a Go method and the like), else the first line that holds it in quotes, else the first that holds it bare. A name that only a script, a test or a
fixture holds prints `name | WEAK MATCH path:line`: it is not a surface of the product. A name found nowhere, or only in a doc, is `name | NOT FOUND`:
a scout cannot invent a surface. Exit 0; the lead drops the NOT FOUND and WEAK MATCH rows. Exit 2 on bad usage.
"""
import json
import os
import re
import subprocess
import sys

KINDS = ("entry", "command", "flag", "route", "event", "env", "config", "manifest", "export", "doc", "ci")
SKIP_DIRS = {"node_modules", "vendor", "dist", "target", "build", ".git", "__pycache__", ".venv", "venv", ".tox", "site-packages"}
TEST = re.compile(r"(^|/)(tests?|__tests__|e2e|spec|testdata|fixtures?|__snapshots__)(/|$)|_test\.|\.test\.|\.spec\.|(^|/)test_[^/]*\.py$|(^|/)conftest\.py$")
SCRIPTS = re.compile(r"(^|/)scripts?/")  # build and smoke scripts: not the product, so a name only they hold is a weak match
MAX_BYTES = 800_000
CAP = {"export": 200, "doc": 100, "ci": 200}
MANIFESTS = {"package.json", "pyproject.toml", "Cargo.toml", "go.mod", "setup.py", "Makefile", "Dockerfile", "compose.yaml", "compose.yml",
             "docker-compose.yml", "docker-compose.yaml", "Taskfile.yml", "Taskfile.yaml"}
TOOLING = re.compile(r"^(\.?(mkdocs|codecov|dependabot|renovate|rustfmt|clippy|deny|cliff|goreleaser|golangci|pre-commit-config|travis|prettierrc|eslintrc|editorconfig|readthedocs|release-please-config)|\.gitlab-ci|\.gitpod|netlify|vercel|fly|app)(\.|$)|(^|/)\.github/|lock\.(ya?ml|toml)$|^(cargo|poetry|pnpm)-", re.I)
CONFIG_EXT = re.compile(r"\.(toml|ya?ml|ini|conf|cfg)$|\.(example|sample)$|(^|/)\.env(\.[\w-]+)?$")
NOISE_EVENTS = {"close", "error", "end", "data", "exit", "open", "message", "SIGINT", "SIGTERM", "SIGHUP", "uncaughtException", "unhandledRejection", "finish", "drain", "readable"}
NOISE_ENV = {"OPTARG", "OPTIND", "OPTERR", "PATH", "HOME", "PWD", "USER", "SHELL", "IFS", "LANG", "TERM", "TMPDIR", "NODE_ENV"}
JS = r"\.(?:[mc]?[jt]sx?|vue)$"

# (kind, file regex, line regex, name group; 0 = the whole line).
PATTERNS = [
    # Python
    ("flag", r"\.py$", r"add_argument\(\s*[\"']([^\"']+)", 1),
    ("flag", r"\.py$", r"@click\.option\(\s*[\"']([^\"']+)", 1),
    ("command", r"\.py$", r"@(?:click|typer)\.(?:command|group)\(|@\w+\.command\(", 0),
    ("route", r"\.py$", r"@\w+\.(?:get|post|put|delete|patch|websocket|route)\(\s*[\"']([^\"']+)", 1),
    ("env", r"\.py$", r"os\.(?:environ(?:\.get)?|getenv)[\[(]\s*[\"'](\w+)", 1),
    ("entry", r"\.py$", r"^if __name__ == [\"']__main__[\"']", 0),
    # Go
    ("entry", r"\.go$", r"^package main\b", 0),
    ("command", r"\.go$", r"\bUse:\s*\"([^\"]+)\"", 1),
    ("flag", r"\.go$", r"(?:Flags\(\)|PersistentFlags\(\)|\bflag|\bpflag)\.\w+P?\(\s*(?:&?[\w.]+,\s*)?\"([\w-]+)\"", 1),
    ("flag", r"\.go$", r"\bcli\.\w+Flag\{[^}]*?\bName:\s*\"([\w-]+)\"", 1),
    ("route", r"\.go$", r"\b(?:HandleFunc|Handle|Get|Post|Put|Delete|Patch|GET|POST|PUT|DELETE)\(\s*\"(/[^\"]*)\"", 1),
    ("route", r"\.go$", r"regexp\.MustCompile\(\s*[`\"](\^?/[^`\"]*)", 1),
    ("env", r"\.go$", r"os\.(?:Getenv|LookupEnv)\(\"(\w+)\"", 1),
    # Rust
    ("command", r"\.rs$", r"#\[command\(([^)]*)\)\]", 1),
    ("route", r"\.rs$", r"#\[(?:get|post|put|delete|patch|head|options)\(\s*\"(/[^\"]*)\"", 1),
    ("env", r"\.rs$", r"env::var(?:_os)?\(\"(\w+)\"", 1),
    # JS, TS
    ("command", JS, r"\.command\(\s*[\"']([^\"']+)", 1),
    ("flag", JS, r"\.(?:option|requiredOption)\(\s*[\"']([^\"']+)", 1),
    ("route", JS, r"\b(?:app|router|api|server)\.(?:get|post|put|delete|patch|use)\(\s*[\"'](/[^\"']*)", 1),
    ("event", JS, r"\b\w+\.on\(\s*[\"']([\w:.-]+)[\"']\s*,\s*(?:async\s*)?(?:\(|function|\w+\s*=>)", 1),
    ("env", JS, r"process\.env\.(\w+)", 1),
    # Shell
    ("flag", r"\.(?:sh|bash|zsh)$|(?:^|/)[^./]+$", r"^\s*(-{1,2}[\w-]+(?:\|-{1,2}[\w-]+)*)\)", 1),
    ("env", r"\.(?:sh|bash|zsh)$|(?:^|/)[^./]+$", r"\$\{([A-Z][A-Z0-9_]+)[:=?-]", 1),
    ("env", r"\.(?:sh|bash|zsh)$|(?:^|/)[^./]+$", r"^\s*export\s+([A-Z][A-Z0-9_]+)=", 1),
    # CI
    ("ci", r"(^|/)\.github/workflows/[^/]+\.ya?ml$|(^|/)\.gitlab-ci\.ya?ml$", r"^\s*-?\s*run:\s*(\S.*)$", 1),
]
PATTERNS = [(k, re.compile(e), re.compile(r), g) for k, e, r, g in PATTERNS]
GO_FLAG_NAME = re.compile(r"^\s*Name:\s*\"([\w-]+)\"")  # a urfave/cli flag with its fields on their own lines: the line above opens `cli.XFlag{`
GO_FLAG_OPEN = re.compile(r"\bcli\.\w+Flag\{\s*$")
BARREL = re.compile(r"(^|/)(__init__\.py|index\.[mc]?[jt]sx?|mod\.[jt]s|lib\.rs|mod\.rs)$")
EXPORT = re.compile(r"^(?:pub (?:async )?(?:fn|struct|enum|trait)|export (?:default )?(?:async )?(?:function|class|const|interface|type)|(?:async )?def|class) ([A-Za-z]\w*)")
GO_EXPORT = re.compile(r"^func (?:\([^)]*\) )?([A-Z]\w*)\(")
CLAP = re.compile(r"#\[(?:arg|clap)\(([^)]*)\)\]")
CLAP_FIELD = re.compile(r"^\s*(?:pub\s+)?(\w+)\s*:")
CLAP_LONG = re.compile(r"\blong\s*=\s*\"([\w-]+)\"")
CLAP_SHORT = re.compile(r"\bshort\s*=\s*'(\w)'")
MAKE_TARGET = re.compile(r"^([A-Za-z0-9_][\w.-]*)\s*:(?![=])")


def list_files(repo):
    """Tracked files when the repo is a git checkout, else every file; build and vendor folders are skipped either way."""
    r = subprocess.run(["git", "-C", repo, "ls-files", "-z"], capture_output=True)
    if r.returncode == 0 and r.stdout:
        files = [f for f in r.stdout.decode("utf-8", errors="replace").split("\0") if f]
    else:
        files = []
        for root, dirs, names in os.walk(repo):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            files += [os.path.relpath(os.path.join(root, n), repo) for n in sorted(names)]
    return sorted(f for f in files if not SKIP_DIRS & set(f.split("/")) and os.path.isfile(os.path.join(repo, f)))


def read_text(repo, f):
    full = os.path.join(repo, f)
    try:
        if os.path.getsize(full) > MAX_BYTES:
            return None
        data = open(full, "rb").read()
    except OSError:
        return None
    return None if b"\0" in data[:4000] else data.decode("utf-8", errors="replace")


class Rows:
    def __init__(self):
        self.rows, self.seen_env = [], set()

    def add(self, kind, name, f, i):
        name = re.sub(r"\s+", " ", name.replace("|", "/")).strip()[:90]
        if kind == "env":
            if name in NOISE_ENV or name in self.seen_env:
                return
            self.seen_env.add(name)
        if kind == "event" and name in NOISE_EVENTS:
            return
        self.rows.append({"kind": kind, "name": name or "?", "file": f, "line": i})


ARGV = re.compile(r"process\.argv|\bparseArgs\b|\byargs\b|\bcommander\b|\bargv\b")
PROGRAM = re.compile(r"\bprogram\s*=\s*['\"]([A-Za-z][\w-]*)['\"]")
USAGE = re.compile(r"['\"`]usage:\s*([A-Za-z][\w-]*)")
CASE = re.compile(r"^\s*case\s+['\"]([\w:-]+)['\"]\s*:")
COMMAND_TEST = re.compile(r"\b(?:command|cmd|verb|subcommand)\s*[!=]==\s*['\"]([\w-]+)['\"]")
OPTION_ENTRY = re.compile(r"^\s*(?:'([\w-]+)'|\"([\w-]+)\"|([A-Za-z_]\w*))\s*:\s*\{\s*type:\s*['\"](?:string|boolean)['\"]")
OPTIONS_OPEN = re.compile(r"\boptions:\s*\{")
OPTION_KEY = re.compile(r"^\s*(?:'([\w-]+)'|\"([\w-]+)\"|([A-Za-z_]\w*))\s*:")


def inline_option_keys(line):
    """The keys of every `options: { a: ..., 'b-c': ... }` on one line, at the top level of the braces."""
    keys = []
    for m in OPTIONS_OPEN.finditer(line):
        depth, start = 1, m.end()
        for j in range(start, len(line)):
            depth += (line[j] == "{") - (line[j] == "}")
            if depth == 0:
                body = line[start:j]
                break
        else:
            body = line[start:]
        top, d, cur = [], 0, ""
        for ch in body:
            d += (ch in "{[(") - (ch in "}])")
            if ch == "," and d == 0:
                top.append(cur)
                cur = ""
            else:
                cur += ch
        top.append(cur)
        for part in top:
            k = OPTION_KEY.match(part)
            if k:
                keys.append(k.group(1) or k.group(2) or k.group(3))
    return keys


def js_cli_rows(rows, f, lines):
    """The command lines and options of a TS/JS file that reads argv: its default program name, `usage: name`, case arms, command tests, parseArgs options."""
    seen = set()
    for i, l in enumerate(lines, 1):
        names = [m.group(1) for m in PROGRAM.finditer(l)] + [m.group(1) for m in USAGE.finditer(l)]
        names += [m.group(1) for m in CASE.finditer(l)] + [m.group(1) for m in COMMAND_TEST.finditer(l)]
        for name in names:
            if name not in seen:
                seen.add(name)
                rows.add("command", name, f, i)
        o = OPTION_ENTRY.match(l)
        for key in ([o.group(1) or o.group(2) or o.group(3)] if o else []) + inline_option_keys(l):
            rows.add("flag", "--" + key, f, i)


def manifest_rows(rows, f, lines):
    base = os.path.basename(f)
    rows.add("manifest", base, f, 1)
    if base == "package.json":
        block = None
        for i, l in enumerate(lines, 1):
            m = re.match(r'^(\s*)"(bin|main|exports|module|scripts)"\s*:\s*(.*)$', l)
            if m and len(m.group(1)) <= 2:
                if m.group(2) == "scripts" and m.group(3).strip().startswith("{") and not m.group(3).strip().endswith("}"):
                    block = len(m.group(1))
                    continue
                rows.add("entry", "%s %s" % (m.group(2), m.group(3).strip().rstrip(",")[:60]), f, i)
                block = None
            elif block is not None:
                s = re.match(r'^(\s*)"([^"]+)"\s*:\s*"', l)
                if s and len(s.group(1)) > block:
                    rows.add("entry", "script %s" % s.group(2), f, i)
                elif re.match(r"^\s*\}", l):
                    block = None
    elif base == "pyproject.toml" or base == "Cargo.toml":
        table = ""
        for i, l in enumerate(lines, 1):
            t = re.match(r"^\[+([\w.-]+)\]+", l)
            if t:
                table = l.strip()
                continue
            k = re.match(r"^([\w.-]+)\s*=", l)
            if k and table in ("[project.scripts]", "[tool.poetry.scripts]"):
                rows.add("entry", "script %s" % k.group(1), f, i)
            elif k and table == "[[bin]]" and k.group(1) == "name":
                rows.add("entry", "bin " + l.split("=", 1)[1].strip().strip('"'), f, i)
    elif base == "Dockerfile":
        for i, l in enumerate(lines, 1):
            if re.match(r"^(ENTRYPOINT|CMD)\b", l):
                rows.add("entry", l, f, i)
    elif base.startswith(("compose", "docker-compose")):
        in_services = False
        for i, l in enumerate(lines, 1):
            if re.match(r"^services:\s*$", l):
                in_services = True
            elif re.match(r"^\S", l):
                in_services = False
            elif in_services and (m := re.match(r"^  ([\w.-]+):\s*$", l)):
                rows.add("entry", "service %s" % m.group(1), f, i)
    elif base == "Makefile":
        for i, l in enumerate(lines, 1):
            m = MAKE_TARGET.match(l)
            if m and not m.group(1).startswith(".") and m.group(1) != "FORCE":
                rows.add("command", "make %s" % m.group(1), f, i)
    elif base.startswith("Taskfile"):
        in_tasks = False
        for i, l in enumerate(lines, 1):
            if re.match(r"^tasks:\s*$", l):
                in_tasks = True
            elif re.match(r"^\S", l):
                in_tasks = False
            elif in_tasks and (m := re.match(r"^  ([\w:.-]+):\s*$", l)):
                rows.add("command", "task %s" % m.group(1), f, i)


def scan(repo):
    rows, files = Rows(), list_files(repo)
    counts = dict.fromkeys(KINDS, 0)
    for f in files:
        base, depth = os.path.basename(f), f.count("/")
        text = read_text(repo, f)
        if text is None:
            continue
        lines = text.split("\n")
        if base in MANIFESTS and depth <= 3 and not TEST.search(f):
            manifest_rows(rows, f, lines)
            continue
        if re.match(r"^(README|CONTRIBUTING|AGENTS|CLAUDE)", base, re.I) and depth == 0 or (re.search(r"\.(md|mdx|rst)$", f) and re.match(r"docs?/", f) and depth <= 3):
            rows.add("doc", base, f, 1)
            continue
        if TEST.search(f):
            continue
        if CONFIG_EXT.search(f) and depth <= 2 and not TOOLING.search(f) and not f.startswith(".github/") and not f.endswith((".lock", ".json")):
            rows.add("config", base, f, 1)
            continue
        is_script = text.startswith("#!") and (re.search(r"\.(sh|bash|zsh)$", f) or "." not in base)
        if is_script:
            rows.add("entry", "script %s" % base, f, 1)
        if base == "__main__.py" or (base == "main.rs" and "src/" in f) or re.match(r".*src/bin/[^/]+\.rs$", f) or re.match(r"(.*/)?cmd/[^/]+/main\.go$", f):
            rows.add("entry", base if depth == 0 else f.rsplit("/", 2)[-2] + "/" + base, f, 1)
        for kind, ext, rx, g in PATTERNS:
            if not ext.search(f):
                continue
            for i, l in enumerate(lines, 1):
                m = rx.search(l)
                if m:
                    rows.add(kind, (m.group(g) if g else l) or l, f, i)
        if re.search(JS, f) and ARGV.search(text):
            js_cli_rows(rows, f, lines)
        if f.endswith(".go"):
            for i, l in enumerate(lines[1:], 2):
                m = GO_FLAG_NAME.match(l)
                if m and GO_FLAG_OPEN.search(lines[i - 2]):
                    rows.add("flag", m.group(1), f, i)
        if f.endswith(".rs"):
            for i, l in enumerate(lines, 1):
                m = CLAP.search(l)
                if m and re.search(r"\b(long|short)\b", m.group(1)):
                    lng = CLAP_LONG.search(m.group(1))
                    if lng:
                        name = "--" + lng.group(1)
                    else:
                        field = next((CLAP_FIELD.match(x).group(1) for x in lines[i:i + 4] if CLAP_FIELD.match(x)), None)
                        sh = CLAP_SHORT.search(m.group(1))
                        if re.search(r"\blong\b", m.group(1)) and field:
                            name = "--" + field.replace("_", "-")
                        elif sh or field:  # a bare `short` is the field's first letter
                            name = "-" + (sh.group(1) if sh else field[0])
                        else:
                            name = "?"
                    rows.add("flag", name, f, i)
        barrel = BARREL.search(f) and depth <= 3
        go_root = f.endswith(".go") and depth == 0
        if barrel or go_root:
            rx = GO_EXPORT if go_root else EXPORT
            for i, l in enumerate(lines, 1):
                m = rx.match(l)
                if m and not m.group(1).startswith("_"):
                    rows.add("export", m.group(1), f, i)
    out, per = [], dict.fromkeys(KINDS, 0)
    for r in sorted(rows.rows, key=lambda r: (KINDS.index(r["kind"]), r["file"], r["line"])):
        per[r["kind"]] += 1
        if per[r["kind"]] <= CAP.get(r["kind"], 10**9):
            out.append(r)
    return out, per


def definition(name):
    n = re.escape(name)
    return re.compile(r"(?:^|[\s;])(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?|class|interface|type|enum|struct|trait|def|fn|func|const|let|var)\s+" + n + r"(?![\w-])"
                      r"|^\s*func\s*\([^)]*\)\s*" + n + r"\s*\(")


KIND_ORDER = {"command": 0, "route": 1, "flag": 2, "event": 3, "env": 4}


def scan_row(rows, name):
    """The row the scan found for a name, or None: its exact name (a flag also by the name before its argument), a command first, then the shallowest file."""
    hits = [r for r in rows if not SCRIPTS.search(r["file"]) and (r["name"] == name or (r["kind"] == "flag" and r["name"].split(" ")[0] == name))]
    return min(hits, key=lambda r: (KIND_ORDER.get(r["kind"], 9), r["file"].count("/"), r["file"], r["line"])) if hits else None


def find_line(files, read, name):
    """(file, line) of the line that defines the name in these files, else the first that holds it in quotes, else the first that holds it bare; None if none."""
    defn = definition(name)
    bare = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")
    quoted = re.compile(r"[\"'`]" + re.escape(name) + r"[\"'`]")
    hit = {"def": None, "quoted": None, "bare": None}
    for f in files:
        for i, l in enumerate(read(f), 1):
            if defn.search(l):
                hit["def"] = (f, i)
                break
            if hit["quoted"] is None and quoted.search(l):
                hit["quoted"] = (f, i)
            elif hit["bare"] is None and bare.search(l):
                hit["bare"] = (f, i)
        if hit["def"]:
            break
    return hit["def"] or hit["quoted"] or hit["bare"]


def resolve(repo, names):
    """[(name, status, "path:line" or None)]: status is "found" (in the product), "weak" (only in a script, a test or a fixture) or None (not found, or only in a doc)."""
    files = [f for f in list_files(repo) if not re.search(r"\.(md|mdx|rst|txt|adoc)$", f) and not f.endswith((".lock", ".json", ".svg", ".map", ".min.js"))]
    product = [f for f in files if not TEST.search(f) and not SCRIPTS.search(f)]
    weak = [f for f in files if TEST.search(f) or SCRIPTS.search(f)]
    cache = {}

    def read(f):
        if f not in cache:
            cache[f] = (read_text(repo, f) or "").split("\n")
        return cache[f]

    rows, _ = scan(repo)
    out = []
    for name in names:
        row = scan_row(rows, name)
        found = (row["file"], row["line"]) if row else find_line(product, read, name)
        if found:
            out.append((name, "found", "%s:%d" % found))
            continue
        found = find_line(weak, read, name)
        out.append((name, "weak", "%s:%d" % found) if found else (name, None, None))
    return out


def main(argv):
    args = [a for a in argv[1:] if a != "--json"]
    names_file = None
    if "--resolve" in args:
        i = args.index("--resolve")
        names_file = args[i + 1] if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    if len(args) != 1 or not os.path.isdir(args[0]) or (("--resolve" in argv) and not (names_file and os.path.isfile(names_file))):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    repo = os.path.realpath(args[0])
    if names_file:
        names = [l.strip() for l in open(names_file, encoding="utf-8", errors="replace") if l.strip() and not l.lstrip().startswith("#")]
        for name, status, where in resolve(repo, names):
            print("%s | %s" % (name, {"found": where, "weak": "WEAK MATCH %s" % where}.get(status, "NOT FOUND")))
        return 0
    rows, per = scan(repo)
    if "--json" in argv:
        print(json.dumps(rows, indent=1))
        return 0
    print("# %s: " % os.path.basename(repo) + ", ".join("%s %d" % (k, per[k]) for k in KINDS if per[k]) + " (%d rows)" % len(rows))
    for r in rows:
        print("%s | %s | %s:%d" % (r["kind"], r["name"], r["file"], r["line"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
