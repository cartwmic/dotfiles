#!/usr/bin/env python3
"""Dependency gate for viz (design principles §2, §3).

Every file under dot_local/share/viz/core/ may import only other files under
core/: no node: builtins, no packages, nothing in adapters/ or viz.mjs. It may
not reach the runtime through the process, Buffer or require globals either.
Run: python3 tests/viz/test_boundaries.py
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(ROOT, "dot_local", "share", "viz", "core")

SPECIFIER = re.compile(
    r"""(?:\bimport\s*(?:[\w*{}\s,$]+\s*from\s*)?|\bexport\s*[\w*{}\s,$]*\s*from\s*|\bimport\s*\(\s*|\brequire\s*\(\s*)"""
    r"""['"]([^'"]+)['"]""")
RUNTIME_GLOBAL = re.compile(r"\b(process|Buffer|require)\b")


def strip_comments(source):
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(^|[^:\\])//[^\n]*", r"\1", source)


def violations(path, source):
    """Return the boundary violations in one core file's source text."""
    found = []
    code = strip_comments(source)
    for spec in SPECIFIER.findall(code):
        if not spec.startswith("."):
            found.append("%s imports %r (builtin or package)" % (path, spec))
            continue
        target = os.path.normpath(os.path.join(os.path.dirname(path), spec))
        if os.path.commonpath([target, CORE]) != CORE:
            found.append("%s imports %r (outside core/)" % (path, spec))
    for name in sorted(set(RUNTIME_GLOBAL.findall(code))):
        found.append("%s uses the runtime global %r" % (path, name))
    return found


def core_files():
    for dirpath, _, names in os.walk(CORE):
        for name in sorted(names):
            if name.endswith((".mjs", ".js", ".cjs")):
                yield os.path.join(dirpath, name)


class CoreBoundaryTest(unittest.TestCase):
    def test_core_imports_only_core(self):
        files = list(core_files())
        self.assertTrue(files, "no core files found under %s" % CORE)
        found = []
        for path in files:
            with open(path) as f:
                found += violations(path, f.read())
        self.assertEqual(found, [])

    def test_gate_catches_outward_imports(self):
        sample = os.path.join(CORE, "sample.mjs")
        bad = (
            "import { readFileSync } from 'node:fs';\n"
            "import x from '../adapters/fs_store.mjs';\n"
            "export { y } from \"../viz.mjs\";\n"
            "const z = await import('child_process');\n"
            "process.stdout.write('x');\n"
        )
        self.assertEqual(len(violations(sample, bad)), 5, violations(sample, bad))
        good = "import { VizError } from './domain.mjs';\n// mentions node: and process in a comment\n"
        self.assertEqual(violations(sample, good), [])


if __name__ == "__main__":
    unittest.main()
