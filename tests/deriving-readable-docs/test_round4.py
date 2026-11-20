"""Batch 6: what the held-out repos (ntfy, uptime-kuma, lapce) showed the general skill lacked. Each test breaks one rule and fails without its change.
Run: python3 -I tests/deriving-readable-docs/test_round4.py"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
SKILL_DIR = SCRIPTS.parent
FIX = HERE / "fixtures/round4"
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True
import early_exits  # noqa: E402


def script(name, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def line_of(text, needle, nth=1):
    hits = [n for n, l in enumerate(text.split("\n"), 1) if needle in l]
    return hits[nth - 1]


def exits_at(text, ext, needle, nth=1):
    """[(line, kind, guard line)] listed above the line that holds `needle`."""
    found = early_exits.early_exits(text, ext, line_of(text, needle, nth))
    assert found is not None and not found.get("unreadable"), found
    return [(e["line"], e["kind"], e["guard"]) for e in found["exits"]]


class GoExitsTest(unittest.TestCase):
    def test_ntfy_message_cache_lists_each_return_under_the_branch_that_holds_it(self):
        """ntfy server.go createMessageCache: the cache-duration 0 return comes before the database-URL return, and the list says which `if` holds each."""
        text = (FIX / "ntfy_cache.go").read_text()
        rows = exits_at(text, ".go", "return message.NewMemStore()")
        self.assertEqual(rows, [(line_of(text, "NewNopStore"), "return", line_of(text, "if conf.CacheDuration == 0")),
                                (line_of(text, "NewPostgresStore"), "return", line_of(text, "else if pool != nil")),
                                (line_of(text, "NewSQLiteStore"), "return", line_of(text, 'else if conf.CacheFile != ""'))])

    SRC = '''package main

import "log"

const raw = `if x { return }`

func run(args []string, f func() error) error { // return {
	if len(args) == 0 {
		return nil
	}
	if err := f(); err != nil {
		return err
	}
	cb := func() int {
		return 7
	}
	go func() {
		return
	}()
	for _, a := range args {
		if a == "" {
			continue
		}
		switch a {
		case "boom":
			panic("boom")
		case "stop", "end":
			os.Exit(2)
		default:
			log.Fatalf("bad %s", a)
		}
		use(a)
	}
	lit := Config{
		Name: "x",
	}
	use(cb, lit)
	return nil
}
'''

    def test_it_lists_return_panic_os_exit_log_fatal_and_continue_with_their_guards(self):
        rows = exits_at(self.SRC, ".go", "use(a)")
        kinds = {(self.SRC.split("\n")[n - 1].strip(), k) for n, k, _ in rows}
        self.assertEqual(kinds, {("return nil", "return"), ("return err", "return"), ("continue", "continue"), ('panic("boom")', "panic"),
                                 ("os.Exit(2)", "os.Exit"), ('log.Fatalf("bad %s", a)', "log.Fatal")})

    def test_a_case_clause_is_the_guard_of_its_exit_and_a_return_in_a_func_literal_is_not_listed(self):
        rows = {self.SRC.split("\n")[n - 1].strip(): g for n, _, g in exits_at(self.SRC, ".go", "use(a)")}
        self.assertEqual(rows['panic("boom")'], line_of(self.SRC, 'case "boom"'))
        self.assertEqual(rows["os.Exit(2)"], line_of(self.SRC, 'case "stop", "end"'))
        self.assertEqual(rows["log.Fatalf(\"bad %s\", a)"], line_of(self.SRC, "default:"))
        self.assertEqual(rows["return err"], line_of(self.SRC, "if err := f(); err != nil"))
        self.assertNotIn("return 7", rows)
        self.assertEqual(len(exits_at(self.SRC, ".go", "use(a)")), 6)

    def test_a_string_or_comment_that_reads_return_or_a_brace_is_not_code(self):
        self.assertEqual(exits_at('package p\n\nfunc f() {\n\t// return {\n\ts := "return }"\n\tr := `return {`\n\tuse(s, r)\n}\n', ".go", "use(s, r)"), [])

    def test_a_process_ending_call_inside_a_func_literal_still_leaves_the_function(self):
        src = "package p\n\nfunc f() {\n\tdefer func() {\n\t\tpanic(\"x\")\n\t}()\n\tuse()\n}\n"
        self.assertEqual([k for _, k, _ in exits_at(src, ".go", "use()")], ["panic"])

    def test_a_label_a_struct_key_and_a_multiline_call_do_not_end_the_function(self):
        src = ("package p\n\nfunc f(a, b int) error {\n\tx := call(a,\n\t\tb)\nouter:\n\tfor {\n\t\tbreak outer\n\t}\n"
               "\ttype T struct {\n\t\tA int\n\t}\n\tif a > 1 {\n\t\treturn errors.New(\"x\")\n\t}\n\treturn use(x)\n}\n")
        self.assertEqual([(k) for _, k, _ in exits_at(src, ".go", "return use(x)")], ["return"])

    def test_unbalanced_braces_are_unreadable_not_a_guess(self):
        found = early_exits.early_exits("package p\n\nfunc f() {\n\tif x {\n\t\treturn\n}\n", ".go", 5)
        self.assertEqual(found, {"unreadable": True})


class RustExitsTest(unittest.TestCase):
    def test_lapce_git_commit_lists_each_question_mark_and_leaves_the_closure_one_out(self):
        """lapce dispatch.rs git_commit: the `?` calls above the Err arm are exits, the one under the Ok arm is guarded by that arm, and the closure's is not an exit."""
        text = (FIX / "lapce_commit.rs").read_text()
        rows = exits_at(text, ".rs", "NotFound => Err(anyhow!(")
        lines = [n for n, _, _ in rows]
        self.assertEqual({k for _, k, _ in rows}, {"?"})
        self.assertIn(line_of(text, "Repository::discover"), lines)
        self.assertIn(line_of(text, "repo.find_tree(tree)?"), lines)
        self.assertIn(line_of(text, ")?;", 1), lines)
        self.assertNotIn(line_of(text, "peel_to_commit()?"), lines)
        by = dict((n, g) for n, _, g in rows)
        self.assertEqual(by[line_of(text, "Repository::discover")], None)
        self.assertEqual(by[line_of(text, "&parents_refs,") + 1], line_of(text, "Ok(signature) => {"))
        self.assertEqual(by[line_of(text, "index.add_path(p.strip_prefix")], line_of(text, "FileDiff::Modified(p) | FileDiff::Added(p) => {"))

    SRC = '''use std::process;

pub trait Sized2: ?Sized {}

fn run<T: ?Sized>(args: &[&str], v: Option<u8>) -> Result<(), E> {
    let c = '{';
    let r = r#"return {"#;
    /* a /* nested */ return */
    let n = v.unwrap_or_else(|| { return 3; });
    let m = v.map(|x| x + 1).ok_or_else(|e| panic!("none"))?;
    let w = foo().map_err(|e| e)?;
    if args.is_empty() {
        bail!("empty");
    }
    ensure!(n > 1, "small");
    match n {
        0 => return Err(E::Zero),
        1 => {
            return Ok(());
        }
        _ => process::exit(3),
    }
    for a in args {
        if a.is_empty() {
            continue;
        }
        use_it(a);
    }
    let _l: &'static str = "x";
    use_all(c, r, m, w);
    Ok(())
}
'''

    def test_it_lists_return_question_mark_bail_ensure_panic_exit_and_continue(self):
        rows = exits_at(self.SRC, ".rs", "use_it(a)")
        text = self.SRC.split("\n")
        got = {(text[n - 1].strip(), k) for n, k, _ in rows}
        self.assertIn(("let m = v.map(|x| x + 1).ok_or_else(|e| panic!(\"none\"))?;", "?"), got)
        self.assertIn(("let m = v.map(|x| x + 1).ok_or_else(|e| panic!(\"none\"))?;", "panic"), got)
        self.assertIn(("let w = foo().map_err(|e| e)?;", "?"), got)
        self.assertIn(('bail!("empty");', "bail!"), got)
        self.assertIn(('ensure!(n > 1, "small");', "ensure!"), got)
        self.assertIn(("0 => return Err(E::Zero),", "return"), got)
        self.assertIn(("return Ok(());", "return"), got)
        self.assertIn(("_ => process::exit(3),", "process::exit"), got)
        self.assertIn(("continue;", "continue"), got)

    def test_a_return_in_a_closure_and_text_in_a_char_raw_string_comment_or_bound_are_not_exits(self):
        rows = exits_at(self.SRC, ".rs", "use_it(a)")
        text = self.SRC.split("\n")
        lines = [text[n - 1] for n, _, _ in rows]
        self.assertFalse([l for l in lines if "unwrap_or_else(|| { return 3; })" in l], lines)
        self.assertFalse([l for l in lines if "nested" in l or "r#" in l or "'{'" in l or "?Sized" in l], lines)

    def test_a_match_arm_is_the_guard_of_its_exit_with_or_without_braces(self):
        rows = {self.SRC.split("\n")[n - 1].strip(): g for n, _, g in exits_at(self.SRC, ".rs", "use_it(a)")}
        self.assertEqual(rows["0 => return Err(E::Zero),"], None)  # the arm and the exit share a line
        self.assertEqual(rows["return Ok(());"], line_of(self.SRC, "1 => {"))
        self.assertEqual(rows['bail!("empty");'], line_of(self.SRC, "if args.is_empty()"))

    def test_a_multiline_arm_without_braces_names_its_arm_as_the_guard(self):
        src = "fn f(x: u8) -> Result<u8, E> {\n    let y = match x {\n        0 =>\n            return Err(E::Zero),\n        _ => 1,\n    };\n    use_it(y);\n    Ok(y)\n}\n"
        self.assertEqual(exits_at(src, ".rs", "use_it(y)"), [(4, "return", 3)])

    def test_an_attribute_does_not_become_the_head_of_the_function(self):
        src = "#[derive(Debug)]\n#[cfg(test)]\nfn f() -> Result<(), E> {\n    g()?;\n    use_it();\n    Ok(())\n}\n"
        found = early_exits.early_exits(src, ".rs", 5)
        self.assertEqual(found["fn_line"], 3)

    def test_a_rust_file_that_does_not_balance_is_unreadable(self):
        self.assertEqual(early_exits.early_exits("fn f() {\n    if a {\n        return;\n}\n", ".rs", 3), {"unreadable": True})


class GuardSheetAppliesToGoAndRustTest(unittest.TestCase):
    """check_citations.py --guards and --audit read Go and Rust exits, so the condition-sheet gate holds for those writers too."""

    def test_the_guard_sheet_has_a_row_for_each_go_exit_above_a_cited_line(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d, "repo")
            (repo / "server").mkdir(parents=True)
            (repo / "server/cache.go").write_text((FIX / "ntfy_cache.go").read_text())
            doc = Path(d, "draft.md")
            doc.write_text("## A4 Cache\n\nWithout a file or database the cache is in memory. `server/cache.go:11` [A4.aaaa]\n")
            code, out, _ = script("check_citations.py", doc, repo, "--guards")
        rows = [l for l in out.splitlines() if l.startswith("guard | ")]
        self.assertEqual([r.split(" | ")[1] for r in rows], ["server/cache.go:5", "server/cache.go:7", "server/cache.go:9"], out)

    def test_an_unmarked_go_guard_fails_the_audit_gate(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d, "repo")
            (repo / "server").mkdir(parents=True)
            (repo / "server/cache.go").write_text((FIX / "ntfy_cache.go").read_text())
            doc = Path(d, "w/draft.md")
            doc.parent.mkdir()
            doc.write_text("## A4 Cache\n\nWithout a file or database the cache is in memory. `server/cache.go:11` [A4.aaaa]\n")
            (doc.parent / "audit.md").write_text('3 | assert: server/cache.go:11 "return message.NewMemStore()" | exits: none | callers: none found | found: nothing | result: HOLDS\n')
            (doc.parent / "choice.md").write_text("cache\n")
            (doc.parent / "evidence.md").write_text('`server/cache.go:11` | "return message.NewMemStore()" | fallback\n')
            (doc.parent / "guards.md").write_text(
                "guard | server/cache.go:5 | return | return message.NewNopStore() | covered:\nguard | server/cache.go:7 | return | x | covered:\nguard | server/cache.go:9 | return | y | covered:\n")
            code, out, _ = script("check_citations.py", doc, repo, "--audit", doc.parent / "audit.md")
        self.assertEqual(code, 1, out)
        self.assertEqual(len(re.findall(r"FAIL guards: guard server/cache.go:\d+ \(return\) is unmarked", out)), 3, out)


class EarlyExitsDocsSayGoAndRustTest(unittest.TestCase):
    def test_the_docs_name_go_and_rust_where_they_name_python_and_ts(self):
        for name in ("scripts/early_exits.py", "scripts/check_citations.py", "references/drafting.md"):
            text = (SKILL_DIR / name).read_text()
            self.assertRegex(text, r"Go", name)
            self.assertRegex(text, r"Rust", name)
        self.assertNotIn("(Python and TS/JS)", (SKILL_DIR / "scripts/check_citations.py").read_text())


if __name__ == "__main__":
    unittest.main()
