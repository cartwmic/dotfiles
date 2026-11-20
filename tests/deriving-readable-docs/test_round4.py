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


# --- lint_main.py: absolute words, who it is for, distinct flags, the glossary ----------------------------------------------
SURFACES = [{"kind": "command", "name": "notes add", "file": "src/cli.py", "line": 3}, {"kind": "flag", "name": "--tag <name>", "file": "src/cli.py", "line": 5}]
CLI = "notes\n\ncommand notes add\n\nflag --tag\n\nlimit 5 notes in one day\n" + "x\n" * 4
TEMPLATE = """# Part 1: In plain English

## What it is

Notes lets you save short notes from the terminal. [A3.a1]
%(who)s

## How to start

Run `notes add` to save your first note. [A4.b1]

## What you can do

%(part1)s

%(extra)s
# Part 2: Appendix

## A3 The product as a whole

Notes saves short notes from the terminal. `src/cli.py:1` [A3.a1]

## A4 Adding notes

The `notes add` command saves a note. `src/cli.py:3` [A4.b1]
%(appendix)s `src/cli.py:7` [A4.b2]
"""


def guide(part1, appendix, who="Who it is for: anyone who takes notes in a terminal. [A3.a1]", extra=""):
    return TEMPLATE % {"part1": part1 + " [A4.b2]" if part1 else "", "appendix": appendix, "who": who, "extra": extra}


def lint(text, *extra):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "src").mkdir()
        (Path(d) / "src/cli.py").write_text(CLI)
        Path(d, "GUIDE.md").write_text(text)
        Path(d, "surfaces.json").write_text(json.dumps(SURFACES))
        code, out, _ = script("lint_main.py", Path(d, "GUIDE.md"), d, "--surfaces", Path(d, "surfaces.json"), *extra)
    return code, out


class AbsoluteWordsTest(unittest.TestCase):
    def absolute(self, part1, appendix):
        code, out = lint(guide(part1, appendix))
        return code, [l for l in out.splitlines() if "FAIL absolute" in l], out

    def test_ntfy_firebase_only_is_not_in_the_tagged_line_so_it_fails(self):
        """ntfy round 1, line 80: the Part 1 sentence says only, the tagged appendix line does not (the check found it overstated)."""
        code, rows, out = self.absolute("The server sends to Firebase only when a Firebase client exists and Firebase is on for that message.",
                                        "`dispatch` sends to Firebase in a goroutine when a Firebase client exists and `opts.firebase` is true.")
        self.assertEqual(code, 1, out)
        self.assertEqual(len(rows), 1, out)
        self.assertIn("only", rows[0])

    def test_ntfy_all_users_and_uptime_kuma_any_method_fail_the_same_way(self):
        _, rows, out = self.absolute("The command sets a rule, and everyone stands for all users.", "`ntfy access` sets a rule, and `everyone` stands for `*`.")
        self.assertEqual(len(rows), 1, out)
        self.assertIn("all:", rows[0])
        _, rows, out = self.absolute("Another program can report in by calling the push address with any HTTP method.", "`/api/push/:pushToken` answers every HTTP method.")
        self.assertEqual(len(rows), 1, out)
        self.assertIn("any:", rows[0])

    def test_the_word_passes_when_a_tagged_appendix_sentence_uses_it(self):
        """ntfy round 1, line 53: the tagged appendix line itself says anything, so this gate cannot fail it (the appendix line is a checker's finding)."""
        code, rows, out = self.absolute("An admin user can do anything.", "`Authorize` lets an admin user do anything.")
        self.assertEqual(rows, [], out)

    def test_the_word_must_match_whole_so_anything_is_not_any_and_unless_is_not_if(self):
        _, rows, out = self.absolute("An admin user can do anything.", "An admin user can do any listed action.")
        self.assertEqual(len(rows), 1, out)
        _, rows, out = self.absolute("It saves a note unless the day is full.", "It saves a note if the day is not full.")
        self.assertEqual(len(rows), 1, out)

    def test_a_word_the_appendix_holds_only_inside_quotes_or_a_name_does_not_count(self):
        _, rows, out = self.absolute("It never saves an empty note.", 'It prints "never" in the log when the note is empty.')
        self.assertEqual(len(rows), 1, out)

    def test_every_listed_word_fails_when_the_appendix_lacks_it(self):
        for word in ("any", "anything", "every", "all", "only", "always", "never", "nothing", "none", "unless"):
            _, rows, out = self.absolute("It %s saves a note on the first day." % word, "It saves a note on the first day.")
            self.assertEqual(len(rows), 1, (word, out))

    def test_an_untagged_glossary_entry_for_an_outside_term_is_not_judged(self):
        text = guide("You keep up to 5 notes in one day.", "It stops after 5 notes in one day.",
                     extra="## Glossary\n\nPub-sub: a pattern where every subscriber gets all the messages.\n")
        code, out = lint(text)
        self.assertEqual(code, 0, out)


class WhoItIsForTest(unittest.TestCase):
    def test_a_guide_with_no_who_it_is_for_line_or_section_fails(self):
        code, out = lint(guide("You keep up to 5 notes in one day.", "It stops after 5 notes in one day.", who=""))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL who-for:", out)

    def test_a_line_that_says_the_repo_does_not_say_passes_when_it_is_tagged(self):
        code, out = lint(guide("You keep up to 5 notes in one day.", "It stops after 5 notes in one day.", who="Who it is for: the README does not say. [A3.a1]"))
        self.assertEqual(code, 0, out)

    def test_a_who_it_is_for_section_passes(self):
        text = guide("You keep up to 5 notes in one day.", "It stops after 5 notes in one day.", who="").replace(
            "## How to start", "## Who it is for\n\nAnyone who takes notes in a terminal. [A3.a1]\n\n## How to start")
        code, out = lint(text)
        self.assertEqual(code, 0, out)

    def test_the_line_still_needs_a_tag_like_any_sentence(self):
        code, out = lint(guide("You keep up to 5 notes in one day.", "It stops after 5 notes in one day.", who="Who it is for: anyone who takes notes."))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL tag:", out)


class DistinctFlagsTest(unittest.TestCase):
    def test_the_same_flag_four_times_is_one_flag_and_four_different_flags_fail(self):
        base = ("Use --tag to tag a note, then --tag again, --tag a third time and --tag a fourth.", "It stops after 5 notes in one day.")
        code, out = lint(guide(*base))
        self.assertEqual(code, 0, out)
        code, out = lint(guide("Use --tag, --color, --due and --pin to set four options on a note.", base[1]))
        self.assertEqual(code, 1, out)
        self.assertIn("4 --flag tokens, limit 3", out)


class GlossaryInCheckCitationsTest(unittest.TestCase):
    def test_an_untagged_outside_term_entry_with_every_or_all_is_not_an_uncited_claim(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src/cli.py").write_text(CLI)
            doc = guide("You keep up to 5 notes in one day.", "It stops after 5 notes in one day.",
                        extra="## Glossary\n\nPub-sub: a pattern where every subscriber gets all the messages.\n")
            Path(d, "GUIDE.md").write_text(doc)
            code, out, _ = script("check_citations.py", Path(d, "GUIDE.md"), d)
        self.assertNotIn("Pub-sub", out)  # not a failure and not a flag for the checkers: it says nothing about the repo
        self.assertEqual(code, 0, out)

    def test_a_tagged_glossary_entry_with_an_overreach_word_is_still_judged(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src/cli.py").write_text(CLI)
            doc = guide("You keep up to 5 notes in one day.", "It stops after 5 notes in one day.", extra="## Glossary\n\nStore: every note goes here. [A3.a1]\n")
            Path(d, "GUIDE.md").write_text(doc)
            code, out, _ = script("check_citations.py", Path(d, "GUIDE.md"), d)
        self.assertIn("flag uncited: every | Store: every note goes here", out)


class SliceWasTest(unittest.TestCase):
    OLD = ("## A4 Notes\n\nIt saves a note. `src/cli.py:3` [A4.aaaa]\nIt stops after 5 notes. `src/cli.py:7` [A4.bbbb]\n"
           "It lists notes. `src/cli.py:3` [A4.cccc]\nIt deletes a note. `src/cli.py:3` [A4.dddd]\n")
    NEW = ("## A4 Notes\n\nIt deletes a note. `src/cli.py:3` [A4.dddd]\nIt saves a note. `src/cli.py:3` [A4.aaaa]\nIt stops after 5 notes a day. `src/cli.py:7` [A4.bbbb]\n"
           "The count is per user. `src/cli.py:7` [A4.eeee]\nIt lists notes. `src/cli.py:3` [A4.cccc]\n")

    def picked(self, *extra, ids="A4.aaaa\n"):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src/cli.py").write_text(CLI)
            Path(d, "GUIDE.md").write_text(self.NEW)
            Path(d, "OLD.md").write_text(self.OLD)
            Path(d, "ids.txt").write_text(ids)
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), d, "--ids", Path(d, "ids.txt"), "--out", Path(d, "o"), *[str(Path(d, x)) if x == "OLD.md" else x for x in extra])
            claims = Path(d, "o/slice-1.claims.txt").read_text() if Path(d, "o/slice-1.claims.txt").exists() else ""
        self.assertEqual(code, 0, err)
        return re.findall(r"A4\.\w{4}", claims)

    def test_without_was_only_the_listed_ids_are_re_checked(self):
        self.assertEqual(self.picked(), ["A4.aaaa"])

    def test_with_was_a_split_off_line_a_reworded_line_and_a_moved_line_are_picked_up_too(self):
        self.assertEqual(sorted(self.picked("--was", "OLD.md")), ["A4.aaaa", "A4.bbbb", "A4.dddd", "A4.eeee"])

    def test_a_line_after_an_edited_or_cut_neighbour_is_as_it_was_and_is_not_picked(self):
        self.assertNotIn("A4.cccc", self.picked("--was", "OLD.md"))

    def test_was_needs_ids_and_a_file(self):
        code, _, err = script("slice.py", "/no/doc.md", "/tmp", "--was", "x.md")
        self.assertEqual(code, 2)


class ScoreOutIsAFileTest(unittest.TestCase):
    REPORT = "Slice: slice-1\nread | 3.1 | HOLDS | a.rs:1\nCounts: claims checked 1; HOLDS 1; WRONG 0; OVERSTATED 0; UNSUPPORTED 0.\n"

    def setup(self, d):
        (Path(d) / "reports").mkdir()
        Path(d, "reports/A.md").write_text(self.REPORT)

    def test_out_writes_the_json_at_the_path_and_the_text_beside_it(self):
        with tempfile.TemporaryDirectory() as d:
            self.setup(d)
            code, out, err = script("score.py", Path(d, "reports"), "--out", Path(d, "score.json"))
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(Path(d, "score.json").read_text())["repos"][0]["claims"], 1)
            self.assertIn("claims", Path(d, "score.txt").read_text())
            self.assertFalse(Path(d, "score").exists())

    def test_a_folder_or_a_name_that_is_not_json_is_a_usage_error_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            self.setup(d)
            Path(d, "score").mkdir()
            for target in (Path(d, "score"), Path(d, "score.txt"), Path(d, "newname")):
                code, out, err = script("score.py", Path(d, "reports"), "--out", target)
                self.assertEqual(code, 2, (target, err))
                self.assertIn("file path that ends in .json, not a folder", err)
            self.assertEqual(list(Path(d, "score").iterdir()), [])
            self.assertFalse(Path(d, "newname").exists())

    def test_lab_out_is_a_file_too(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "beh.txt").write_text("B1 | a.rs:1 |\n")
            Path(d, "draft.md").write_text("## A4 S\n\nIt reads one file. `a.rs:1` [A4.aaaa]\n")
            Path(d, "a.rs").write_text("x\n")
            code, out, err = script("score.py", "--lab", Path(d, "beh.txt"), Path(d, "draft.md"), d, "--out", Path(d, "lab.json"))
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(Path(d, "lab.json").read_text())["behaviours"], 1)
            code, out, err = script("score.py", "--lab", Path(d, "beh.txt"), Path(d, "draft.md"), d, "--out", Path(d, "labdir"))
            self.assertEqual(code, 2, err)


class LintBriefTest(unittest.TestCase):
    BRIEF = "Seat: writer, Opus\n\nSection A4 Notes.\n\nFiles:\n- src/cli.py\n- `src/lib/`\n\nBudget 600 words.\n"

    def lint(self, brief, files=("src/cli.py", "src/lib/a.py")):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "brief.md").write_text(brief)
            repo = Path(d, "r")
            for f in files:
                (repo / f).parent.mkdir(parents=True, exist_ok=True)
                (repo / f).write_text("x\n")
            return script("lint_brief.py", Path(d, "brief.md"), repo)

    def test_a_brief_whose_files_all_exist_passes(self):
        code, out, _ = self.lint(self.BRIEF)
        self.assertEqual(code, 0, out)

    def test_a_file_the_repo_does_not_have_fails_and_is_named_with_its_brief_line(self):
        code, out, _ = self.lint(self.BRIEF.replace("- src/cli.py", "- src/cli.py\n- src/missing.py"))
        self.assertEqual(code, 1, out)
        self.assertIn("brief.md:7: FAIL file: src/missing.py does not exist in the repo", out)

    def test_a_path_outside_the_repo_fails(self):
        code, out, _ = self.lint(self.BRIEF.replace("- src/cli.py", "- ../brief.md"))
        self.assertEqual(code, 1, out)
        self.assertIn("outside the repo", out)

    def test_a_brief_with_no_files_list_fails_and_paths_on_one_line_are_each_checked(self):
        code, out, _ = self.lint("Seat: writer\n\nSection A4.\n")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL files", out)
        code, out, _ = self.lint("Files: src/cli.py, src/nope.py\n\nx\n")
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("FAIL file:"), 1, out)

    def test_the_list_ends_at_the_first_blank_line(self):
        code, out, _ = self.lint("Files:\n- src/cli.py\n\nRead src/nowhere.py for the README.\n")
        self.assertEqual(code, 0, out)


class BatchSixDocsTest(unittest.TestCase):
    """The method files say what the batch-6 scripts now do."""
    ref = staticmethod(lambda n: (SKILL_DIR / "references" / n).read_text(encoding="utf-8"))
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    def test_drafting_names_precedence_in_the_same_sentence(self):
        text = self.ref("drafting.md")
        self.assertRegex(text, r"If no earlier case applies")
        self.assertRegex(text, r"(?i)position alone")

    def test_the_front_writer_reads_the_whole_subsection_of_each_tag(self):
        self.assertRegex(self.ref("drafting.md"), r"(?i)tag's whole appendix subsection")

    def test_the_front_writer_brief_names_absolute_words_and_the_1000_cap(self):
        text = self.ref("drafting.md")
        self.assertRegex(text, r"(?i)absolute word")
        self.assertRegex(text, r"1,000 words at every step")

    def test_the_front_writer_brief_asks_for_a_who_it_is_for_sentence(self):
        self.assertIn("Who it is for:", self.ref("drafting.md"))

    def test_writers_write_evidence_and_audit_files_by_hand(self):
        self.assertRegex(self.ref("drafting.md"), r"(?i)no script generates or fills")

    def test_the_check_brief_is_version_8_and_counts_the_next_sentence_in_the_appendix(self):
        text = self.ref("check-brief.md")
        self.assertIn("version 8", text)
        self.assertRegex(text, r"(?i)appendix claim: a condition[^\n]*very next sentence of the same doc line")
        self.assertRegex(text, r"(?i)log: v8")

    def test_fix_rounds_says_what_to_cut_over_1000_words(self):
        text = self.ref("fix-rounds.md")
        self.assertRegex(text, r"(?i)over 1,000 words")
        self.assertRegex(text, r"(?i)never cut How to start or the Who it is for")
        self.assertIn("--was", text)

    def test_the_reader_check_runs_on_the_shipped_guide(self):
        text = self.ref("reader-check.md")
        self.assertRegex(text, r"(?i)shipped guide")
        self.assertIn("#4966", text)

    def test_skill_step_2_scout_writes_surface_names_and_groups(self):
        self.assertIn("groups.txt", self.skill)
        self.assertRegex(self.skill, r"never a file path")
        self.assertIn("lint_brief.py", self.skill)


if __name__ == "__main__":
    unittest.main()
