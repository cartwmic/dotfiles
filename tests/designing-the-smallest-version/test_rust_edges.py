"""repo_facts.py reads Rust: `mod x;`, `use crate::`, `use super::`, `use <workspace crate>::` and Cargo dependencies make edges.
Run: python3 -I tests/designing-the-smallest-version/test_rust_edges.py"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = tempfile.mkdtemp(prefix="state-")  # the script logs each run (runlog.py): keep these runs out of the real log
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

SKILLS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills"
REPO_FACTS = SKILLS / "designing-the-smallest-version/scripts/repo_facts.py"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

CORE = "crates/core/src/"
APP = "crates/app/src/"

FILES = {
    "Cargo.toml": '[workspace]\nmembers = ["crates/core", "crates/app"]\n\n[workspace.dependencies]\ndemo-core = { path = "crates/core" }\n',
    "crates/core/Cargo.toml": '[package]\nname = "demo-core"\nversion = "0.1.0"\n',
    "crates/core/src/lib.rs": "pub mod model;\npub mod store;\n#[cfg(test)]\nmod tests;\nmod util {\n    pub fn f() {}\n    mod tests {\n        use super::*;\n    }\n}\n",
    "crates/core/src/model.rs": ('//! Example: `use crate::store::Store;`\n'
                                 'pub mod nested;\npub struct Item;\n'
                                 'pub fn text() -> &\'static str {\n    "use crate::store::Store;\\n"\n}\n'),
    "crates/core/src/model/nested.rs": "use super::Item;\nuse crate::store::{self, Store};\npub fn g(_: Item, _: Store) {}\n",
    "crates/core/src/tests.rs": "fn t() {}\n",
    "crates/core/src/store.rs": "use crate::model::Item;\npub struct Store;\npub fn h(_: Item) {\n    crate::model::nested::g(Item, Store);\n}\n",
    "crates/app/Cargo.toml": ('[package]\nname = "demo-app"\nversion = "0.1.0"\n\n[dependencies]\n'
                              'demo-core = { workspace = true }\nserde = "1"\n'),
    "crates/app/src/main.rs": "mod cli;\nuse demo_core::store::Store;\nuse serde::Serialize;\nfn main() { let _ = Store; }\n",
    "crates/app/src/cli.rs": "// require(\"lodash\") is TypeScript: no package here\nuse demo_core::model::Item;\nuse Kind::*;\nenum Kind { A }\npub fn run(_: Item) {}\n",
    "crates/app/tests/it.rs": "use demo_core::model::Item;\n#[test]\nfn t() { let _ = Item; }\n",
}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def make_repo(root, files):
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "fixture")


def facts(repo, *args):
    res = subprocess.run([sys.executable, "-B", str(REPO_FACTS), str(repo), *args], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


class RustEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rust_edges-"))
        make_repo(cls.tmp / "ws", FILES)
        cls.facts = facts(cls.tmp / "ws")
        cls.edges = {tuple(e) for e in cls.facts["edges"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def has(self, a, b):
        self.assertIn((a, b), self.edges)

    def test_rust_is_a_parsed_extension(self):
        self.assertIn(".rs", self.facts["parsed"])
        self.assertNotIn(".rs", self.facts["unparsed"])

    def test_mod_declaration_reaches_the_file(self):
        self.has(CORE + "lib.rs", CORE + "model.rs")
        self.has(CORE + "model.rs", CORE + "model/nested.rs")
        self.has(APP + "main.rs", APP + "cli.rs")
        self.assertEqual(sorted(map(tuple, self.facts["mod_edges"])), sorted([
            (CORE + "lib.rs", CORE + "model.rs"), (CORE + "lib.rs", CORE + "store.rs"), (CORE + "lib.rs", CORE + "tests.rs"),
            (CORE + "model.rs", CORE + "model/nested.rs"), (APP + "main.rs", APP + "cli.rs")]))

    def test_use_crate_and_use_super(self):
        self.has(CORE + "store.rs", CORE + "model.rs")  # use crate::model::Item
        self.has(CORE + "model/nested.rs", CORE + "model.rs")  # use super::Item
        self.has(CORE + "model/nested.rs", CORE + "store.rs")  # use crate::store::{self, Store}

    def test_a_path_written_inline_in_code_is_an_edge(self):
        self.has(CORE + "store.rs", CORE + "model/nested.rs")  # crate::model::nested::g(...)

    def test_use_of_a_workspace_crate_reaches_its_file(self):
        self.has(APP + "main.rs", CORE + "store.rs")
        self.has(APP + "cli.rs", CORE + "model.rs")
        self.has("crates/app/tests/it.rs", CORE + "model.rs")

    def test_cargo_dependency_between_members(self):
        self.has("crates/app/Cargo.toml", "crates/core/Cargo.toml")  # demo-core = { workspace = true } and the workspace gives its path

    def test_doc_comment_and_string_make_no_edge(self):
        self.assertNotIn((CORE + "model.rs", CORE + "store.rs"), self.edges)

    def test_super_inside_an_inline_mod_is_the_file_itself(self):
        self.assertFalse([e for e in self.edges if e[0] == CORE + "lib.rs" and e[1] != e[0] and e[1].endswith("util.rs")])
        self.assertNotIn((CORE + "lib.rs", CORE + "lib.rs"), self.edges)

    def test_an_outside_crate_is_external_not_an_edge(self):
        self.assertEqual(self.facts["external_packages"]["crates/app"], {"serde": 1})

    def test_mod_edges_are_not_a_cycle_but_a_real_loop_is(self):
        # lib.rs declares model.rs and model.rs uses nothing from lib.rs. nested.rs and store.rs use each other.
        self.assertEqual([c["members"] for c in self.facts["cycles"]["file"]], [[CORE + "model/nested.rs", CORE + "store.rs"]])

    def test_a_tests_rs_file_counts_as_test_code(self):
        self.assertEqual(self.facts["sizes"]["crates/core"]["test_lines"], 1)

    def test_the_notes_say_what_the_rust_edges_are(self):
        note = self.facts["notes"]["rust"]
        self.assertIn("`mod x;`", note)
        self.assertIn("mod_edges", note)
        self.assertIn("rust_imports.py", note)

    def test_scope_report_counts_the_edges(self):
        scoped = facts(self.tmp / "ws", "--scope", "crates/core/src/**")
        self.assertEqual(scoped["edge_count"], len(self.edges))
        self.assertEqual(scoped["mod_edge_count"], 5)
        store = next(f for f in scoped["scope"]["files"] if f["file"] == CORE + "store.rs")
        self.assertIn(CORE + "model.rs", store["imports"])

ROOT_CRATE = {
    "Cargo.toml": '[package]\nname = "solo"\nversion = "0.1.0"\n',
    "src/lib.rs": "mod a;\n",
    "src/a.rs": "mod b;\npub struct A;\n",
    "src/a/b.rs": "use super::A;\npub fn f(_: A) {}\n",
}


class ModEdgesAndDirCycles(unittest.TestCase):
    def test_a_child_dir_that_uses_super_is_not_a_dir_cycle(self):
        tmp = Path(tempfile.mkdtemp(prefix="rust_root-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        make_repo(tmp / "solo", ROOT_CRATE)
        out = facts(tmp / "solo")
        dir_pairs = {(r["from"], r["to"]) for r in out["dir_edges"]}
        self.assertEqual(dir_pairs, {("src", "src/a"), ("src/a", "src")})  # both edges are listed
        self.assertEqual(out["cycles"], {"dir": [], "file": []})  # but `mod b;` over `use super::` is no loop

    def test_a_parents_own_use_of_its_child_is_left_out_of_the_cycles_too(self):
        tmp = Path(tempfile.mkdtemp(prefix="rust_parent_use-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        make_repo(tmp / "solo", dict(ROOT_CRATE, **{"src/a.rs": "mod b;\nuse b::f;\npub struct A;\n"}))
        out = facts(tmp / "solo")
        self.assertIn(["src/a.rs", "src/a/b.rs"], out["edges"])
        self.assertEqual(out["cycles"]["file"], [])  # the `use b::f` pair is the `mod b;` pair

LAYOUT = {
    "Cargo.toml": '[workspace]\nmembers = ["crates/a", "crates/b"]\n',
    "crates/a/Cargo.toml": '[package]\nname = "lay-a"\nversion = "0.1.0"\n\n[dependencies]\nlay-b = { path = "../b" }\n',
    "crates/a/src/lib.rs": "pub fn f() {}\n",
    "crates/b/Cargo.toml": '[package]\nname = "lay-b"\nversion = "0.1.0"\n',
    "crates/b/src/lib.rs": '#[path = "other/place.rs"]\npub mod renamed;\npub mod inner;\n',
    "crates/b/src/other/place.rs": "pub struct P;\n",
    "crates/b/src/inner/mod.rs": "pub mod leaf;\nuse self::leaf::deep::Z;\npub fn g(_: Z) {}\n",
    "crates/b/src/inner/leaf.rs": "pub mod deep;\n",
    "crates/b/src/inner/leaf/deep.rs": "pub struct Z;\n",
    "crates/b/src/shared.rs": "pub fn s() {}\n",
    "crates/b/tests/it.rs": '#[path = "../src/shared.rs"]\nmod shared;\n#[test]\nfn t() { shared::s(); }\n',
}


class NamedCases(unittest.TestCase):
    """`use self::`, a direct `path =` dependency, `#[path]` modules and `x/mod.rs`: each has an edge here that only that case can make."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rust_layout-"))
        make_repo(cls.tmp / "lay", LAYOUT)
        cls.facts = facts(cls.tmp / "lay")
        cls.edges = {tuple(e) for e in cls.facts["edges"]}
        cls.mods = {tuple(e) for e in cls.facts["mod_edges"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_use_self_reaches_the_module_it_names(self):
        edge = ("crates/b/src/inner/mod.rs", "crates/b/src/inner/leaf/deep.rs")  # only `use self::leaf::deep::Z` links these two
        self.assertIn(edge, self.edges)
        self.assertNotIn(edge, self.mods)

    def test_a_direct_path_dependency_is_a_cargo_edge(self):
        self.assertIn(("crates/a/Cargo.toml", "crates/b/Cargo.toml"), self.edges)  # lay-b = { path = "../b" }, no `workspace = true`

    def test_a_path_attribute_names_the_file_of_a_module(self):
        self.assertIn(("crates/b/src/lib.rs", "crates/b/src/other/place.rs"), self.mods)
        self.assertIn(("crates/b/tests/it.rs", "crates/b/src/shared.rs"), self.mods)  # how a test crate pulls in the source it tests

    def test_a_module_may_be_x_slash_mod_rs_and_its_children_sit_beside_it(self):
        self.assertIn(("crates/b/src/lib.rs", "crates/b/src/inner/mod.rs"), self.mods)
        self.assertIn(("crates/b/src/inner/mod.rs", "crates/b/src/inner/leaf.rs"), self.mods)


class NoTomllibNeededWithoutCargo(unittest.TestCase):
    def test_a_repo_without_cargo_toml_runs_where_tomllib_is_missing(self):
        tmp = Path(tempfile.mkdtemp(prefix="no_toml-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        make_repo(tmp / "py", {"a.py": "import b\n", "b.py": "x = 1\n"})
        code = ("import sys, runpy; sys.modules['tomllib'] = None; sys.argv = ['repo_facts.py', %r]; runpy.run_path(%r, run_name='__main__')"
                % (str(tmp / "py"), str(REPO_FACTS)))
        res = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["edges"], [["a.py", "b.py"]])


if __name__ == "__main__":
    unittest.main()
