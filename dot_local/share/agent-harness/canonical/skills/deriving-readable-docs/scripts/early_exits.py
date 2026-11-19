#!/usr/bin/env python3
"""List the early exits that sit between the start of a function and a line inside it.

usage: early_exits.py <file> <line>

A sentence about what a function does is true on the path the writer followed and often false on another: an
earlier `return`, `throw`, `continue` or `break` skips the cited line. For a line inside a function this lists,
from the function's first line down to (not including) that line, each statement that leaves the function or the
loop around the line (given a range, check_citations.py asks for its last line and marks the exits that sit inside
the range): return, throw / raise, continue and break (only when the loop also holds the line),
process.exit / sys.exit. A `return` inside a nested callback or inner function is not an exit of the function and
is left out. Each exit prints with its line, its source and, when the exit line does not show it, the `if`,
`else` or `catch` line it sits under (a Python exit in an `else:` says "in the else of" that `if`).

Python files are read with the `ast` module. TS/JS files (.ts .tsx .js .jsx .mjs .cjs .mts .cts) are read with a
small scanner, not a parser: strings, template literals, regex literals and comments are skipped, and each `{`
is classed as a function body, loop, switch, condition or plain block from the words before it. Braces that do not
balance (a stray `}` too), or a Python syntax error, print "exits not listed" instead of a guess. Other file types print
nothing. Known gaps: text in JSX that reads `return` or `throw` is listed as an exit; an exit is a statement, so a
condition that skips code without leaving (an `if/else if` chain, a ternary, a flag test) is not listed.

Exit 0 always (it is a reading aid). 2: usage error. Stdlib only. As a library: `early_exits(text, ext, line)`
returns None when the file type is not read or the line is in no function, else a dict
`{"unreadable": True}` or `{"fn_line": N, "exits": [{"line", "kind", "guard"}]}`.
"""
import ast
import os
import re
import sys

JS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
PY_EXT = {".py"}


# --- TS/JS ----------------------------------------------------------------------------------------------------
IDENT = re.compile(r"[A-Za-z_$\u0080-￿][\w$\u0080-￿]*")
NUMBER = re.compile(r"\d[\w.]*")
# A `/` after one of these starts a regex literal; after a name, number, `)` or `]` it divides.
REGEX_AFTER = {"(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "=>", "+", "-", "*", "%", "<", ">", "~", "^",
               "return", "typeof", "case", "do", "else", "in", "of", "throw", "new", "delete", "void", "yield", "await"}


def skip_quote(src, i):
    q, j = src[i], i + 1
    while j < len(src) and src[j] != q and src[j] != "\n":
        j += 2 if src[j] == "\\" else 1
    return min(j + 1, len(src))


def skip_template(src, i):
    j = i + 1
    while j < len(src):
        if src[j] == "\\":
            j += 2
        elif src[j] == "`":
            return j + 1
        elif src.startswith("${", j):
            j = skip_braces(src, j + 2)
        else:
            j += 1
    return len(src)


def skip_braces(src, j):
    """From just after a `${`, to just after its closing `}`."""
    depth = 1
    while j < len(src):
        c = src[j]
        if c in "'\"":
            j = skip_quote(src, j)
            continue
        if c == "`":
            j = skip_template(src, j)
            continue
        depth += (c == "{") - (c == "}")
        j += 1
        if depth == 0:
            break
    return j


def skip_regex(src, i):
    """End of a regex literal that starts at i, or -1 when the line ends first (then it was a division)."""
    j, in_class = i + 1, False
    while j < len(src) and src[j] != "\n":
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            j += 1
            while j < len(src) and (src[j].isalpha()):
                j += 1
            return j
        j += 1
    return -1


def js_tokens(src):
    """[(text, line)]: names and punctuation; a string, template, number or regex is one placeholder token."""
    toks, i, line, n = [], 0, 1, len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            line, i = line + 1, i + 1
        elif c in " \t\r":
            i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += src.count("\n", i, j)
            i = j
        elif c in "'\"" or c == "`":
            j = skip_quote(src, i) if c != "`" else skip_template(src, i)
            toks.append(("<str>", line))
            line += src.count("\n", i, j)
            i = j
        elif c == "/" and (not toks or toks[-1][0] in REGEX_AFTER) and skip_regex(src, i) > 0:
            toks.append(("<re>", line))
            i = skip_regex(src, i)
        else:
            m = IDENT.match(src, i) or NUMBER.match(src, i)
            if m:
                toks.append((m.group(0), line))
                i = m.end()
            else:
                two = src[i:i + 2]
                tok = two if two in ("=>", "?.") else c
                toks.append((tok, line))
                i += len(tok)
    return toks


def matching_open(head):
    """Index in head of the `(` that matches the last token `)`, or -1."""
    depth = 0
    for k in range(len(head) - 1, -1, -1):
        depth += (head[k] == ")") - (head[k] == "(")
        if depth == 0:
            return k
    return -1


def classify(head):
    """The kind of a `{` from the tokens since the last `;`, `{` or `}`: func, loop, switch, cond, else or block."""
    if not head:
        return "block"
    last = head[-1]
    if last == "=>":
        return "func"
    if last in ("else", "try", "finally", "do", "catch"):
        return {"else": "else", "do": "loop", "catch": "cond"}.get(last, "block")
    if last != ")":
        # `function f(a): Promise<void> {` and `(a): T {`: a `)`, a colon and then a type (no `{`, `;` or `=`)
        for k in range(len(head) - 2, -1, -1):
            if head[k] == ")":
                tail = head[k + 1:]
                if len(tail) > 1 and tail[0] == ":" and not set(tail) & {"=", ";", "(", "?", "<str>"} and tail.count("<") == tail.count(">"):
                    head, last = head[:k + 1], ")"
                break
            if head[k] in ("(", "{", "}", ";"):
                break
    if last != ")":
        return "obj" if last in ("=", "(", ",", ":", "[", "?", "return", "||", "&&", "??", "<", "+") else "block"
    k = matching_open(head)
    word = head[k - 1] if k > 0 else ""
    if word == "await" and k > 1:
        word = head[k - 2]
    if word in ("for", "while"):
        return "loop"
    if word == "switch":
        return "switch"
    if word in ("if", "catch"):
        return "cond"
    if word == "with":
        return "block"
    return "func"


def js_blocks_and_events(src):
    """Return (blocks, events, balanced). A block: dict(kind, open, close, head). An event is an exit token."""
    toks = js_tokens(src)
    blocks, stack, events = [], [], []
    head, stmt, stray = [], None, False
    for i, (t, line) in enumerate(toks):
        if stmt is None and t not in (",", ")"):
            stmt = line
        if t == "{":
            b = {"kind": classify(head), "open": line, "close": float("inf"), "head": stmt, "outer": (head, stmt)}
            blocks.append(b)
            stack.append(b)
            head, stmt = [], None
        elif t == "}":
            closed = stack.pop() if stack else None
            stray = stray or closed is None
            if closed:
                closed["close"] = line
            if closed and closed["kind"] == "obj":
                head, stmt = closed["outer"]  # an object literal or type is part of the statement around it
                head.append("<obj>")
            else:
                head, stmt = [], None
        elif t == ";" and head.count("(") <= head.count(")"):  # not the `;` inside `for (a; b; c)`
            head, stmt = [], None
        elif t == "," and head.count("(") <= head.count(")"):  # the next entry of an object or list starts its own line label
            head.append(t)
            stmt = None
        else:
            prev = toks[i - 1][0] if i else ""
            kind = None
            if prev != "." and t in ("return", "throw", "continue", "break") and (toks[i + 1][0] if i + 1 < len(toks) else "") != ":":  # not `o.return` or the key `return:`
                kind = t
            elif t == "exit" and prev == "." and i > 1 and toks[i - 2][0] in ("process", "Deno", "Bun"):
                kind = "process.exit"
            if kind:
                func = next((b for b in reversed(stack) if b["kind"] == "func"), None)
                loops = ("loop",) if kind == "continue" else ("loop", "switch")
                brk = next((b for b in reversed(stack) if b["kind"] in loops), None) if kind in ("continue", "break") else None
                cond = next((b for b in reversed(stack) if b["kind"] in ("cond", "else")), None)
                events.append({"kind": kind, "line": line, "stmt": stmt if prev in (")", "else") else line, "func": func, "brk": brk, "cond": cond})
            head.append(t)
    return blocks, events, not stack and not stray


def js_exits(src, line):
    blocks, events, balanced = js_blocks_and_events(src)
    if not balanced:
        return {"unreadable": True}
    encl = [b for b in blocks if b["open"] < line <= b["close"]]
    funcs = [b for b in encl if b["kind"] == "func"]
    if not funcs:
        return None
    fn = max(funcs, key=lambda b: b["open"])
    out = []
    for e in events:
        if e["func"] is not fn or e["line"] >= line:
            continue
        if e["kind"] in ("continue", "break"):
            b = e["brk"]
            if not (b and b["kind"] == "loop" and b["open"] < line <= b["close"]):
                continue  # a loop (or a switch) that closed before the line does not change the path to it
        guard = None
        if e["stmt"] != e["line"]:
            guard = e["stmt"]  # `if (x)` on one line, the exit on the next (only read after `)` or `else`)
        elif e["cond"] is not None and e["cond"]["open"] >= fn["open"] and e["cond"]["head"] != e["line"]:
            guard = e["cond"]["head"]
        out.append({"line": e["line"], "kind": e["kind"], "guard": guard})
    return {"fn_line": fn["head"], "exits": out}


# --- Python ---------------------------------------------------------------------------------------------------
EXIT_CALLS = {("sys", "exit"), ("os", "_exit"), ("os", "abort"), (None, "exit"), (None, "quit"), (None, "_exit")}
FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def exit_call(node):
    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
        return False
    f = node.value.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return (f.value.id, f.attr) in EXIT_CALLS
    return isinstance(f, ast.Name) and (None, f.id) in EXIT_CALLS


def py_exits(src, line):
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError):
        return {"unreadable": True}
    funcs = [n for n in ast.walk(tree) if isinstance(n, FUNCS) and n.lineno < line <= n.end_lineno]
    if not funcs:
        return None
    fn = max(funcs, key=lambda n: n.lineno)
    out = []

    def visit(node, chain):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, FUNCS + (ast.Lambda, ast.ClassDef)):
                continue  # an exit in an inner function or class is not an exit of this function
            if getattr(child, "lineno", line) < line:
                kind = {ast.Return: "return", ast.Raise: "raise", ast.Continue: "continue", ast.Break: "break"}.get(type(child))
                if kind in ("continue", "break"):
                    loop = next((a for a in reversed(chain) if isinstance(a, (ast.For, ast.AsyncFor, ast.While))), None)
                    if not (loop and loop.lineno < line <= loop.end_lineno):
                        kind = None  # a loop that closed before the line does not change the path to it
                elif kind is None and exit_call(child):
                    kind = "exit"
                if kind:
                    k = max((i for i, a in enumerate(chain) if isinstance(a, (ast.If, ast.ExceptHandler))), default=None)
                    guard = chain[k] if k is not None else None
                    below = (chain + [child])[k + 1] if k is not None else None  # the part of the `if` the exit sits in
                    out.append({"line": child.lineno, "kind": kind, "guard": guard.lineno if guard and guard.lineno != child.lineno else None,
                                "else": isinstance(guard, ast.If) and below in guard.orelse})
            visit(child, chain + [child])

    visit(fn, [fn])
    return {"fn_line": fn.lineno, "exits": sorted(out, key=lambda e: e["line"])}


def early_exits(text, ext, line):
    ext = ext.lower()
    if ext in PY_EXT:
        return py_exits(text, line)
    if ext in JS_EXT:
        return js_exits(text, line)
    return None


# --- printing -------------------------------------------------------------------------------------------------
def short(text, width=110):
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 1] + "…"


def render(found, lines, line, first=None):
    """The sheet text for the cited lines that end at `line` (and start at `first`, if given): a header, then one row
    per exit, marked when it sits inside the cited lines; None when nothing is to be said."""
    if found is None:
        return None
    if found.get("unreadable"):
        return "   (early exits not listed: this file could not be read as code)"
    fn = short(lines[found["fn_line"] - 1].strip()) if 0 < found["fn_line"] <= len(lines) else "?"
    exits = found["exits"]
    if not exits:
        return "   (no early exits between the start of `%s` (line %d) and line %d)" % (fn, found["fn_line"], line)
    rows = ["   early exits between the start of `%s` (line %d) and line %d; each can skip the line:" % (fn, found["fn_line"], line)]
    for e in exits:
        row = "%6d  %-12s %s" % (e["line"], e["kind"], short(lines[e["line"] - 1].strip()))
        if e["guard"]:
            row += "    [%s line %d: %s]" % ("in the else of" if e.get("else") else "under", e["guard"], short(lines[e["guard"] - 1].strip(), 70))
        if first is not None and e["line"] >= first:
            row += "    [inside the cited lines]"
        rows.append(row)
    return "\n".join(rows)


def main(argv):
    if len(argv) != 3 or not os.path.isfile(argv[1]) or not argv[2].isdigit():
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    with open(argv[1], "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    line = int(argv[2])
    out = render(early_exits(text, os.path.splitext(argv[1])[1], line), text.splitlines(), line)
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
