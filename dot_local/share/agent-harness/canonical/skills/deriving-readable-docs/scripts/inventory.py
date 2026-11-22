#!/usr/bin/env python3
"""List the literals a user or an operator meets in a repo, for the listers of an extend pass. Reads files only; no repo code is run.

usage: inventory.py <repo> [--json]

Prints one row per literal, `kind | name | path:line`, grouped by kind. Every row is a literal line of the repo, so it is a safe `path:line` to cite. Kinds:
  message  a string literal of two or more words in a raise or throw, an HTTP answer (send, json, Response, detail=, http.Error), a log call at info level or above
           (info, warn, error, console.log, println, bail!, Errorf, errors.New), or a panic. A debug or trace line is not one.
  header   a header the code reads (`headers["X-Api-Key"]`, `req.header("X-Admin-Token")`, `Header.Get("Authorization")`) and the `Bearer` scheme of an auth check.
  route    the paths of surfaces.py (its `route` rows), so one file holds them all.
  default  a setting and the value it has when nothing sets it: `os.environ.get("X", "v")`, `process.env.X ?? v`, `${X:-v}`, `default=v` of an argument, a Go flag, a `KEY=value` line of a
           .env or .example file.
  limit    a named number that caps a size, a time or a count: a constant or variable whose name holds max, min, limit, cap, timeout, ttl, size, retr(y), batch, depth, length,
           interval, delay, backoff, threshold, quota, expir(e), capacity or budget, set to a number (`MAX_RESULTS = 50`, `DEFAULT_TIMEOUT_MS = 30_000`, `const MAX: u32 = 5;`).
Python, TypeScript, JavaScript, Go, Rust and shell are read by one line at a time, with no parser. Test files, fixtures, comments, vendored folders and docs are left out. A message
split over several lines is missed, and a literal in another form is too: it is a reading aid for a lister, not the truth. At most 200 rows of a kind are printed, the first by file and line.

--json prints the rows as a JSON array of {kind, name, file, line}.
Exit 0; 2 on bad usage. Stdlib only.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from surfaces import SCRIPTS, TEST, list_files, read_text, scan  # noqa: E402

KINDS = ("message", "header", "route", "default", "limit")
CAP = 200
SKIP_EXT = re.compile(r"\.(md|mdx|rst|txt|adoc|lock|json|svg|map|min\.js|png|jpe?g|gif|ico|woff2?|pdf)$", re.I)
CODE_EXT = re.compile(r"\.(py|[mc]?[jt]sx?|vue|go|rs|sh|bash|zsh|java|kt|rb|php|cs|swift)$|(^|/)[^./]+$")
CONFIG = re.compile(r"\.(ya?ml|toml|ini|conf|cfg|env)$|(^|/)\.env(\.[\w-]+)?$|\.(example|sample)$")
EXAMPLE = re.compile(r"\.(example|sample)$|(^|/)\.env(\.[\w-]+)?$")
COMMENT = re.compile(r"^\s*(#|//|\*|/\*|--|;)")
LITERAL = re.compile(r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'|`([^`]*)`")
# What a line must do outside its literals for a literal on it to be a message: raise or throw, answer, or log at info or above.
MESSAGE = re.compile(r"\b(?:raise|throw|panic|abort|fatal|bail|anyhow|println|eprintln|print|Errorf|Error|Exception|HTTPException|Response|JSONResponse|send|json|detail|message|msg|"
                     r"(?:logger|logging|log|console|slog|LOG)\s*\.\s*(?:info|warn|warning|error|exception|critical|fatal|log|print\w*|fatal\w*|panic\w*)|"
                     r"(?:info|warn|warning|error|critical)!|errors\s*\.\s*New|http\s*\.\s*Error)\b\s*!?\s*\(?")
QUIET = re.compile(r"\b(?:debug|trace|verbose)\b|\.debug\s*\(|debug!|trace!", re.I)
HEADER_READ = re.compile(r"""(?:[Hh]eaders?(?:\s*\.\s*(?:get|getlist|get_all))?\s*[\[(]|\.\s*(?:header|getHeader|get_header)\s*\(|Header\s*\.\s*Get\s*\()\s*["']([A-Za-z][\w-]*)["']""")
BEARER = re.compile(r"""["'](Bearer|Basic|Token)\s?["']""")
PY_ENV_DEFAULT = re.compile(r"""(?:os\.environ\.get|os\.getenv|environ\.get|getenv)\(\s*["'](\w+)["']\s*,\s*([^,)]+?)\s*\)""")
JS_ENV_DEFAULT = re.compile(r"""process\.env(?:\.(\w+)|\[["'](\w+)["']\])\s*(?:\?\?|\|\|)\s*([^;,)]+?)\s*[;,)]?\s*$""")
SHELL_DEFAULT = re.compile(r"""\$\{([A-Z][A-Z0-9_]*):-([^}]*)\}""")
FLAG_DEFAULT = re.compile(r"""\bflag\s*\.\s*\w+\(\s*"([\w-]+)"\s*,\s*([^,]+?)\s*,""")
ARG_DEFAULT = re.compile(r"""(?:add_argument|click\.option|\.option)\(\s*["']-{0,2}([\w-]+)["'].*?\bdefault\s*=\s*([^,)]+)""")
ENV_FILE_LINE = re.compile(r"""^\s*(?:export\s+)?([A-Za-z_][\w.]*)\s*[=:]\s*(\S.*?)\s*$""")
LIMIT_WORDS = "max|min|limit|cap|timeout|ttl|size|retr(?:y|ies)|batch|depth|length|interval|delay|backoff|threshold|quota|expir\\w*|capacity|budget"
LIMIT = re.compile(r"""^\s*(?:export\s+|pub(?:\([^)]*\))?\s+)?(?:(?:static|const|final|let|var|val|private|public|readonly)\s+)*(?:[\w<>\[\]]+\s+)?"""
                   r"""(\w*(?:%s)\w*)\s*(?::\s*[\w<>\[\]&' ]+?)?\s*:?=\s*(-?\d[\d_]*(?:\.\d+)?(?:\s*[*+/-]\s*\d[\d_]*)*)\s*[;,]?\s*(?:#.*|//.*)?$""" % LIMIT_WORDS, re.I)
LIMIT_NAME = re.compile(r"(?:%s)" % LIMIT_WORDS, re.I)


def literals(line):
    """([text of each string literal], the line with each literal emptied)."""
    found = [next(g for g in m.groups() if g is not None) for m in LITERAL.finditer(line)]
    return found, LITERAL.sub('""', line)


def message_like(text):
    words = [w for w in text.split() if re.search(r"[A-Za-z]", w)]
    return len(words) >= 2 and len(text) >= 8 and not re.fullmatch(r"[\w./:-]+", text) and "\n" not in text


class Rows:
    def __init__(self):
        self.rows, self.seen = [], set()

    def add(self, kind, name, f, i):
        name = re.sub(r"\s+", " ", name.replace("|", "/")).strip()[:90]
        key = (kind, name)
        if not name or key in self.seen:
            return
        self.seen.add(key)
        self.rows.append({"kind": kind, "name": name, "file": f, "line": i})


def code_rows(rows, f, lines):
    for i, line in enumerate(lines, 1):
        if COMMENT.match(line):
            continue
        texts, bare = literals(line)
        if texts and MESSAGE.search(bare) and not QUIET.search(bare):
            for t in texts:
                if message_like(t):
                    rows.add("message", t, f, i)
        for m in HEADER_READ.finditer(line):
            rows.add("header", m.group(1), f, i)
        for m in BEARER.finditer(line):
            rows.add("header", m.group(1), f, i)
        for rx in (PY_ENV_DEFAULT, JS_ENV_DEFAULT, SHELL_DEFAULT):
            m = rx.search(line)
            if m:
                g = [x for x in m.groups() if x is not None]
                rows.add("default", "%s = %s" % (g[0], g[1].strip().strip("\"'")), f, i)
        m = FLAG_DEFAULT.search(line) or ARG_DEFAULT.search(line)
        if m:
            rows.add("default", "%s = %s" % (m.group(1), m.group(2).strip().strip("\"'")), f, i)
        m = LIMIT.match(line)
        if m and LIMIT_NAME.search(m.group(1)):
            rows.add("limit", "%s = %s" % (m.group(1), re.sub(r"\s+", " ", m.group(2))), f, i)


def config_rows(rows, f, lines):
    example = bool(EXAMPLE.search(f))
    for i, line in enumerate(lines, 1):
        if COMMENT.match(line):
            continue
        m = SHELL_DEFAULT.search(line)
        if m:
            rows.add("default", "%s = %s" % (m.group(1), m.group(2)), f, i)
        elif example and (m := ENV_FILE_LINE.match(line)) and "=" in line:
            rows.add("default", "%s = %s" % (m.group(1), m.group(2).strip("\"'")), f, i)


def scan_inventory(repo):
    rows = Rows()
    for f in list_files(repo):
        if SKIP_EXT.search(f) or TEST.search(f) or SCRIPTS.search(f):
            continue
        text = read_text(repo, f)
        if text is None:
            continue
        lines = text.split("\n")
        if CONFIG.search(f) and not CODE_EXT.search(f):
            config_rows(rows, f, lines)
        elif CODE_EXT.search(f):
            code_rows(rows, f, lines)
    surface_rows, _ = scan(repo)
    for r in surface_rows:
        if r["kind"] == "route":
            rows.add("route", r["name"], r["file"], r["line"])
    out, per = [], dict.fromkeys(KINDS, 0)
    for r in sorted(rows.rows, key=lambda r: (KINDS.index(r["kind"]), r["file"], r["line"])):
        per[r["kind"]] += 1
        if per[r["kind"]] <= CAP:
            out.append(r)
    return out, per


def main(argv):
    args = [a for a in argv[1:] if a != "--json"]
    if len(args) != 1 or not os.path.isdir(args[0]):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    repo = os.path.realpath(args[0])
    rows, per = scan_inventory(repo)
    if "--json" in argv:
        print(json.dumps(rows, indent=1))
        return 0
    print("# %s: " % os.path.basename(repo) + ", ".join("%s %d" % (k, per[k]) for k in KINDS if per[k]) + " (%d rows)" % len(rows))
    for r in rows:
        print("%s | %s | %s:%d" % (r["kind"], r["name"], r["file"], r["line"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
