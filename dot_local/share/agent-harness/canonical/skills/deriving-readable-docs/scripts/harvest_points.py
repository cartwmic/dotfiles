#!/usr/bin/env python3
"""List a repo's validation points (tests, scenarios, journeys) as a JSON array.

usage: harvest_points.py <repo>

Each point: id (P1.., in file then line order), name, kind, file (repo-relative, posix), line (1-based),
framework (a guess), context (the enclosing describe/class/feature, may be empty).
kind is syntactic: "test" (a test function or case), "scenario" (a Gherkin scenario) or
"journey-file" (a whole file named like a journey, e2e, acceptance or smoke script that has no extractable points).
Same repo, same output. Reads files only; stdlib only.
"""
import json
import os
import re
import sys

SKIP_DIRS = {
    ".git", "node_modules", "target", "dist", "build", "vendor", "__pycache__", ".venv", "venv", ".tox",
    ".next", ".nuxt", "out", ".cache", ".mypy_cache", ".pytest_cache", "coverage", "site-packages", ".gradle", "Pods",
}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e", "cypress", "integration", "acceptance", "features"}
JS_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
CODE_EXT = JS_EXT | {".py", ".rs", ".go", ".rb", ".ex", ".exs", ".sh", ".bash", ".java", ".kt", ".cs", ".php", ".swift", ".c", ".cc", ".cpp", ".cxx"}
JOURNEY_NAME = re.compile(r"(journey|e2e|acceptance|smoke)", re.I)
MAX_BYTES = 2_000_000


def indent_of(line):
    return len(line) - len(line.lstrip(" \t"))


class Stack:
    """Names of enclosing groups, popped by indentation."""

    def __init__(self):
        self.items = []

    def push(self, indent, name):
        self.pop_to(indent)
        self.items.append((indent, name))

    def pop_to(self, indent):
        while self.items and self.items[-1][0] >= indent:
            self.items.pop()

    def context(self, indent):
        self.pop_to(indent)
        return " > ".join(n for _, n in self.items)


def point(name, kind, line, framework, context=""):
    return {"name": name.strip(), "kind": kind, "line": line, "framework": framework, "context": context}


# --- per-language scanners: (text lines, path parts) -> list of points -------------------------------

PY_DEF = re.compile(r"^(\s*)(?:async\s+)?def\s+(test\w*)\s*\(")
PY_CLASS = re.compile(r"^(\s*)class\s+(\w+)")


def scan_python(lines, rel, text):
    base = os.path.basename(rel)
    parts = rel.split("/")[:-1]
    testish = (base.startswith("test_") or base.endswith("_test.py") or base == "tests.py"
               or any(p in TEST_DIRS for p in parts) or "TestCase" in text or "pytest" in text)
    if not testish:
        return []
    framework = "unittest" if "unittest" in text and "TestCase" in text else "pytest"
    stack, out = Stack(), []
    for i, line in enumerate(lines, 1):
        m = PY_CLASS.match(line)
        if m:
            stack.push(len(m.group(1)), m.group(2))
            continue
        m = PY_DEF.match(line)
        if m:
            out.append(point(m.group(2), "test", i, framework, stack.context(len(m.group(1)))))
    return out


RS_ATTR = re.compile(r"^\s*#\[\s*(?:test|[\w:]+::test|rstest|test_case\b.*|wasm_bindgen_test)\s*(?:\(.*)?\]")
RS_FN = re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)")


def scan_rust(lines, rel, text):
    out, seen = [], set()
    for i, line in enumerate(lines):
        if RS_ATTR.match(line):
            for j in range(i + 1, min(i + 8, len(lines))):
                m = RS_FN.match(lines[j])
                if m:
                    if j not in seen:  # stacked #[test_case(..)] lines name one fn: list it once
                        seen.add(j)
                        out.append(point(m.group(1), "test", j + 1, "rust-test"))
                    break
    return out


GO_FN = re.compile(r"^func\s+(Test\w*)\s*\(")


def scan_go(lines, rel, text):
    if not rel.endswith("_test.go"):
        return []
    return [point(m.group(1), "test", i, "go-test") for i, line in enumerate(lines, 1) if (m := GO_FN.match(line))]


JS_CALL = re.compile(
    r"^(\s*)(?:await\s+)?(describe|it|test|suite|specify)((?:\.[A-Za-z]+)*)\s*\(\s*(['\"`])((?:\\.|(?!\4).)*)\4")
JS_EACH = re.compile(
    r"^(\s*)(describe|it|test)\.each\b.*?\)\s*\(\s*(['\"`])((?:\\.|(?!\3).)*)\3")


def js_framework(text):
    for needle, name in (("@playwright/test", "playwright"), ("vitest", "vitest"), ("node:test", "node:test"),
                         ("bun:test", "bun:test"), ("cypress", "cypress"), ("mocha", "mocha"), ("jest", "jest")):
        if needle in text:
            return name
    return "js-test"


def scan_js(lines, rel, text):
    base = os.path.basename(rel)
    parts = rel.split("/")[:-1]
    testish = (re.search(r"\.(test|spec)\.", base) or any(p in TEST_DIRS for p in parts)
               or re.search(r"(vitest|jest|mocha|node:test|bun:test|@playwright/test|cypress)", text))
    if not testish:
        return []
    framework = js_framework(text)
    stack, out = Stack(), []
    for i, line in enumerate(lines, 1):
        m = JS_CALL.match(line)
        if m:
            indent, fn, mods, name = len(m.group(1)), m.group(2), m.group(3), m.group(5)
        else:
            m = JS_EACH.match(line)
            if not m:
                continue
            indent, fn, mods, name = len(m.group(1)), m.group(2), ".each", m.group(4)
        if fn in ("describe", "suite") or mods.endswith(".describe"):
            stack.push(indent, name)
        elif fn in ("it", "test", "specify") and not mods.endswith((".step", ".use", ".beforeEach", ".afterEach", ".beforeAll", ".afterAll")):
            out.append(point(name, "test", i, framework, stack.context(indent)))
    return out


RB_CALL = re.compile(r"^(\s*)(describe|context|feature|it|specify|scenario|example)\s*\(?\s*(?:(['\"])((?:\\.|(?!\3).)*)\3|([A-Z][\w:]*))")
RB_DEF = re.compile(r"^(\s*)def\s+(test_\w+)")


def scan_ruby(lines, rel, text):
    base = os.path.basename(rel)
    parts = rel.split("/")[:-1]
    if not (base.endswith(("_spec.rb", "_test.rb")) or any(p in TEST_DIRS for p in parts)):
        return []
    framework = "rspec" if re.search(r"\b(RSpec|describe|context)\b", text) else "minitest"
    stack, out = Stack(), []
    for i, line in enumerate(lines, 1):
        m = RB_CALL.match(line)
        if m:
            indent, fn, name = len(m.group(1)), m.group(2), m.group(4) or m.group(5)
            if fn in ("describe", "context", "feature"):
                stack.push(indent, name)
            else:
                out.append(point(name or "", "test", i, framework, stack.context(indent)))
            continue
        m = RB_DEF.match(line)
        if m:
            out.append(point(m.group(2), "test", i, "minitest", stack.context(len(m.group(1)))))
    return out


EX_CALL = re.compile(r'^(\s*)(describe|test)\s+"((?:\\.|[^"\\])*)"')


def scan_elixir(lines, rel, text):
    if not rel.endswith("_test.exs"):
        return []
    stack, out = Stack(), []
    for i, line in enumerate(lines, 1):
        m = EX_CALL.match(line)
        if not m:
            continue
        indent, fn, name = len(m.group(1)), m.group(2), m.group(3)
        if fn == "describe":
            stack.push(indent, name)
        else:
            out.append(point(name, "test", i, "exunit", stack.context(indent)))
    return out


BATS = re.compile(r"""^\s*@test\s+(['"])((?:\\.|(?!\1).)*)\1""")
SH_FN = re.compile(r"^(?:function\s+)?(test_\w+)\s*(?:\(\))?\s*\{?\s*$")


def scan_shell(lines, rel, text):
    out = []
    for i, line in enumerate(lines, 1):
        m = BATS.match(line)
        if m:
            out.append(point(m.group(2), "test", i, "bats"))
    if not out and rel.endswith((".sh", ".bash")):
        base = os.path.basename(rel)
        parts = rel.split("/")[:-1]
        if base.startswith("test") or any(p in TEST_DIRS for p in parts):
            out = [point(m.group(1), "test", i, "shell") for i, line in enumerate(lines, 1) if (m := SH_FN.match(line))]
    return out


GH_SCENARIO = re.compile(r"^\s*(Scenario Outline|Scenario Template|Scenario|Example)\s*:\s*(.*)$")
GH_FEATURE = re.compile(r"^\s*Feature\s*:\s*(.*)$")


def scan_gherkin(lines, rel, text):
    feature, out = "", []
    for i, line in enumerate(lines, 1):
        m = GH_FEATURE.match(line)
        if m:
            feature = m.group(1)
            continue
        m = GH_SCENARIO.match(line)
        if m:
            out.append(point(m.group(2), "scenario", i, "gherkin", feature))
    return out


JAVA_ATTR = re.compile(r"^\s*@(?:Test|ParameterizedTest|RepeatedTest|TestFactory)\b")
JAVA_FN = re.compile(r"(?:\bvoid|\bfun)\s+(?:`([^`]+)`|(\w+))\s*\(")
CLASS_DECL = re.compile(r"^(\s*)(?:[\w@()]+\s+)*?(?:class|object)\s+(\w+)")


def scan_junit(lines, rel, text):
    stack, out, seen = Stack(), [], set()
    for i, line in enumerate(lines):
        m = CLASS_DECL.match(line)
        if m:
            stack.push(len(m.group(1)), m.group(2))
        if JAVA_ATTR.match(line):
            for j in range(i, min(i + 8, len(lines))):
                m = JAVA_FN.search(lines[j])
                if m:
                    if j not in seen:
                        seen.add(j)
                        out.append(point(m.group(1) or m.group(2), "test", j + 1, "junit", stack.context(indent_of(lines[i]))))
                    break
    return out


CS_ATTR = re.compile(r"^\s*\[\s*(Fact|Theory|Test|TestCase|TestMethod)\b")
CS_FN = re.compile(r"\b(\w+)\s*(?:<[^>]*>)?\s*\(")
CS_CLASS = re.compile(r"^(\s*)(?:[\w]+\s+)*?class\s+(\w+)")


def scan_csharp(lines, rel, text):
    stack, out, seen = Stack(), [], set()
    for i, line in enumerate(lines):
        m = CS_CLASS.match(line)
        if m:
            stack.push(len(m.group(1)), m.group(2))
        m = CS_ATTR.match(line)
        if not m:
            continue
        framework = {"Fact": "xunit", "Theory": "xunit", "Test": "nunit", "TestCase": "nunit", "TestMethod": "mstest"}[m.group(1)]
        for j in range(i + 1, min(i + 8, len(lines))):
            if lines[j].lstrip().startswith("["):
                continue
            f = CS_FN.search(lines[j])
            if f:
                if j not in seen:
                    seen.add(j)
                    out.append(point(f.group(1), "test", j + 1, framework, stack.context(indent_of(lines[i]))))
                break
    return out


GTEST = re.compile(r"^\s*(TEST|TEST_F|TEST_P|TYPED_TEST|TYPED_TEST_P)\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)")
CATCH = re.compile(r"""^\s*(?:TEST_CASE|SCENARIO)\s*\(\s*"((?:\\.|[^"\\])*)\"""")


def scan_cpp(lines, rel, text):
    out = []
    for i, line in enumerate(lines, 1):
        m = GTEST.match(line)
        if m:
            out.append(point("%s.%s" % (m.group(2), m.group(3)), "test", i, "googletest", m.group(2)))
            continue
        m = CATCH.match(line)
        if m:
            out.append(point(m.group(1), "test", i, "catch2"))
    return out


SWIFT_XC = re.compile(r"^\s*(?:override\s+|public\s+|private\s+)*func\s+(test\w*)\s*\(")
SWIFT_CLASS = re.compile(r"^(\s*)(?:[\w]+\s+)*?(?:class|struct)\s+(\w+)")
SWIFT_TESTING = re.compile(r"^\s*@Test\b")
SWIFT_FN = re.compile(r"\bfunc\s+(\w+)\s*\(")


def scan_swift(lines, rel, text):
    xctest, testing = "XCTest" in text, "import Testing" in text
    if not (xctest or testing):
        return []
    stack, out, seen = Stack(), [], set()
    for i, line in enumerate(lines):
        m = SWIFT_CLASS.match(line)
        if m:
            stack.push(len(m.group(1)), m.group(2))
        m = SWIFT_XC.match(line) if xctest else None
        if m and i not in seen:
            seen.add(i)
            out.append(point(m.group(1), "test", i + 1, "xctest", stack.context(indent_of(line))))
            continue
        if testing and SWIFT_TESTING.match(line):
            for j in range(i, min(i + 4, len(lines))):
                f = SWIFT_FN.search(lines[j])
                if f:
                    if j not in seen:
                        seen.add(j)
                        out.append(point(f.group(1), "test", j + 1, "swift-testing", stack.context(indent_of(lines[i]))))
                    break
    return out


SCANNERS = {".py": scan_python, ".rs": scan_rust, ".go": scan_go, ".rb": scan_ruby, ".ex": scan_elixir,
            ".exs": scan_elixir, ".sh": scan_shell, ".bash": scan_shell, ".bats": scan_shell, ".feature": scan_gherkin,
            ".java": scan_junit, ".kt": scan_junit, ".cs": scan_csharp, ".swift": scan_swift,
            ".c": scan_cpp, ".cc": scan_cpp, ".cpp": scan_cpp, ".cxx": scan_cpp, ".h": scan_cpp, ".hpp": scan_cpp}
SCANNERS.update({ext: scan_js for ext in JS_EXT})


def first_comment(lines):
    for line in lines[:15]:
        s = line.strip().lstrip("#/*-! ").strip()
        if s and not s.startswith(("bookends:", "usr/bin", "/usr/bin", "env ")) and not line.startswith("#!"):
            return s
    return ""


def harvest(repo):
    found = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            scanner = SCANNERS.get(ext)
            journeyish = ext in CODE_EXT and JOURNEY_NAME.search(fn)
            if not scanner and not journeyish:
                continue
            try:
                if os.path.islink(full) or os.path.getsize(full) > MAX_BYTES:
                    continue
                with open(full, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            rel = os.path.relpath(full, repo).replace(os.sep, "/")
            lines = text.splitlines()
            pts = scanner(lines, rel, text) if scanner else []
            if not pts and journeyish:
                pts = [point(os.path.splitext(fn)[0], "journey-file", 1, "unknown", first_comment(lines))]
            for p in pts:
                p["file"] = rel
                found.append(p)
    found.sort(key=lambda p: (p["file"], p["line"]))
    ordered = []
    for n, p in enumerate(found, 1):
        ordered.append({"id": "P%d" % n, "name": p["name"], "kind": p["kind"], "file": p["file"], "line": p["line"],
                        "framework": p["framework"], "context": p["context"]})
    return ordered


def main(argv):
    if len(argv) != 2 or not os.path.isdir(argv[1]):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    json.dump(harvest(argv[1]), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
