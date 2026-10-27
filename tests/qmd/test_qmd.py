"""QMD install, collections and skill (docs/qmd.md). No qmd binary needed: renders the real chezmoi source.

The real-qmd proof (index, search, hybrid query, byte-identical index.yml) is tests/qmd/proof.sh; it needs the models and is not run in CI.
"""
import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PIN = REPO / "dot_config/mise/conf.d/qmd.toml"
INDEX = REPO / "dot_config/qmd/index.yml.tmpl"
SKILL = REPO / "dot_local/share/agent-harness/canonical/skills/searching-with-qmd/SKILL.md"
BOOTSTRAP = REPO / "run_onchange_after_10_mise_bootstrap.sh.tmpl"

PERSONAL_ONLY = [
    ".config/mise/conf.d/qmd.toml",
    ".config/qmd/index.yml",
    ".local/share/agent-harness/canonical/skills/searching-with-qmd/SKILL.md",
]
# What qmd 2.8.3 itself writes as the models block; the template carries it so qmd leaves the file byte-identical.
MODELS = """models:
  embed: hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
  generate: hf:tobil/qmd-query-expansion-1.7B-gguf/qmd-query-expansion-1.7B-q4_k_m.gguf
  rerank: hf:ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/qwen3-reranker-0.6b-q8_0.gguf
"""


class Chezmoi:
    """chezmoi against the repo with a minimal config (no read-source-state hook) and a throwaway HOME."""

    def __init__(self, profile):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.cfg = Path(self.tmp.name) / "chezmoi.yaml"
        self.cfg.write_text("data:\n  profile: %s\n" % profile)
        self.env = dict(os.environ, HOME=str(self.home))

    def run(self, *args, stdin=None):
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(self.cfg), "--config-format", "yaml",
                            "--destination", str(self.home), *args],
                           input=stdin, capture_output=True, text=True, env=self.env, timeout=120)
        self.last = r
        if r.returncode:
            raise AssertionError("chezmoi %s failed: %s" % (args, r.stderr))
        return r.stdout

    def close(self):
        self.tmp.cleanup()


class PinTest(unittest.TestCase):
    def test_exact_pin_and_nothing_else(self):
        cfg = tomllib.loads(PIN.read_text())
        self.assertEqual(cfg, {"tools": {"npm:@tobilu/qmd": "2.8.3"}})
        self.assertRegex(cfg["tools"]["npm:@tobilu/qmd"], r"^\d+\.\d+\.\d+$")

    def test_pin_is_not_in_the_shared_mise_config(self):
        # The shared config.toml reaches the work and Termux profiles; only the personal-only conf.d file may name qmd.
        self.assertNotIn("qmd", (REPO / "dot_config/mise/config.toml").read_text().lower())


class ProfileMatrixTest(unittest.TestCase):
    def managed(self, profile):
        c = Chezmoi(profile)
        try:
            return set(c.run("managed").split())
        finally:
            c.close()

    def test_personal_gets_the_files(self):
        m = self.managed("personal")
        for p in PERSONAL_ONLY:
            self.assertIn(p, m)

    def test_work_and_termux_get_nothing(self):
        for profile in ("axon-work-computer", "termux"):
            m = self.managed(profile)
            self.assertEqual([p for p in m if "qmd" in p], [], profile)

    def test_bootstrap_script_hashes_the_pin_on_personal_only(self):
        # A hash line on the other profiles would rerun their bootstrap once for a file they never get.
        outs = {}
        for profile in ("personal", "axon-work-computer", "termux"):
            c = Chezmoi(profile)
            try:
                outs[profile] = c.run("execute-template", stdin=BOOTSTRAP.read_text())
            finally:
                c.close()
        self.assertRegex(outs["personal"], r"# Hash \(personal-only QMD pin\): [0-9a-f]{64}\n")
        self.assertNotIn("QMD", outs["axon-work-computer"])
        self.assertNotIn("QMD", outs["termux"])
        # The hash block sits between "# Hash:" and the blank line; off personal that gap must be unchanged, or the script reruns.
        self.assertRegex(outs["termux"], r"# Hash: [0-9a-f]{64}\n\nset -eu")


class IndexTemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = Chezmoi("personal")
        cls.home = c.home
        try:
            cls.out = c.run("execute-template", stdin=INDEX.read_text())
        finally:
            c.close()

    def test_is_in_the_format_qmd_writes_back(self):
        # qmd rewrites index.yml on every run: comments and blank lines vanish and a models block is appended.
        # If the managed file differed, chezmoi would flag it as drifted after the first qmd call.
        lines = self.out.splitlines()
        self.assertFalse([l for l in lines if l.lstrip().startswith("#")], "comments are dropped by qmd")
        self.assertFalse([l for l in lines if not l.strip()], "blank lines are dropped by qmd")
        self.assertFalse([l for l in lines if "\t" in l])
        self.assertTrue(self.out.endswith(MODELS))
        self.assertTrue(lines[0].startswith("global_context: "))
        self.assertEqual(lines[1], "collections:")

    def test_collections(self):
        names = re.findall(r"^  ([a-z0-9-]+):$", self.out.split("models:")[0], re.M)
        self.assertEqual(names[:2], ["notes", "repo-dotfiles"])
        self.assertEqual(names[-2:], ["sessions", "recaps"])
        for n in names:
            self.assertTrue(n in ("notes", "sessions", "recaps") or n.startswith("repo-"), n)
        self.assertEqual(len(names), len(set(names)))
        home = str(self.home)
        self.assertIn("    path: %s/tmp\n    pattern: \"*/*.md\"" % home, self.out)
        self.assertIn("    path: %s/.local/share/chezmoi\n" % home, self.out)
        self.assertIn("    path: %s/.local/share/qmd-corpus/sessions\n" % home, self.out)
        self.assertIn("    path: %s/.local/share/qmd-corpus/recaps\n" % home, self.out)

    def test_masks_and_contexts(self):
        # Parse each collection block; a wrong mask would silently index nothing (or everything).
        blocks = re.findall(r"^  ([a-z0-9-]+):\n    path: (.*)\n    pattern: (.*)\n    context:\n      /: (.*)$",
                            self.out.split("\nmodels:")[0], re.M)
        by = {b[0]: b for b in blocks}
        self.assertEqual(len(blocks), len(re.findall(r"^    path: ", self.out, re.M)), "every block parsed")
        self.assertEqual(by["notes"][2], '"*/*.md"')
        self.assertEqual(by["sessions"][2], '"**/*.md"')
        self.assertEqual(by["recaps"][2], '"**/*.md"')
        self.assertEqual(by["repo-dotfiles"][2], '"**/README.md,**/AGENTS.md,docs/**/*.md"')
        for name, _path, pattern, ctx in blocks:
            if name.startswith("repo-"):
                self.assertEqual(pattern, '"**/README.md,**/AGENTS.md,docs/**/*.md"', name)
            self.assertTrue(ctx.strip(), name)

    def test_repo_collections_exist_only_for_checkouts_present(self):
        for name in ("coordinator", "retro", "loop-engine", "cartwmic-homelab-v2", "budget-steward"):
            present = Path("/Volumes/Workshop/macbook/git", name).exists()
            self.assertEqual("  repo-%s:\n" % name in self.out, present, name)

    def test_every_path_is_absolute_and_every_collection_has_a_context(self):
        paths = re.findall(r"^    path: (.*)$", self.out, re.M)
        self.assertTrue(paths)
        self.assertTrue(all(p.startswith("/") for p in paths), paths)
        self.assertEqual(len(re.findall(r"^    context:$", self.out, re.M)), len(paths))


class SkillTest(unittest.TestCase):
    text = SKILL.read_text()

    def test_frontmatter(self):
        m = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", self.text)
        self.assertTrue(m)
        self.assertEqual(m.group(1), SKILL.parent.name)
        self.assertRegex(m.group(1), r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(m.group(2)), 1024)

    def test_it_stays_short_and_static(self):
        self.assertLessEqual(len(self.text.splitlines()), 30)
        self.assertLessEqual(len(self.text), 2600)
        # No dates, versions or counts that would go stale.
        self.assertNotRegex(self.text, r"2\d{3}-\d\d-\d\d(?!/<)")

    def test_it_warns_about_hybrid_and_names_the_cheap_path(self):
        t = self.text
        self.assertIn('qmd query "', t)
        self.assertIn("5-28 s", t)
        self.assertIn("1-5 GB", t)
        self.assertRegex(t, r"(?i)never run it in parallel, in a loop")
        self.assertIn('qmd search "', t)
        self.assertRegex(t, r"0\.2-1 s")

    def test_it_does_not_hand_out_heavy_or_unbuilt_commands(self):
        t = self.text
        self.assertRegex(t, r"Do not run `qmd update`, `qmd embed`, `qmd pull` or `qmd mcp`")
        self.assertNotIn("qmd-refresh", t)  # lands in a later PR; the skill is updated there
        self.assertNotRegex(t, r"(?i)primer|inject")


class DocTest(unittest.TestCase):
    def test_readme_links_the_doc_and_doc_exists(self):
        self.assertTrue((REPO / "docs/qmd.md").is_file())
        self.assertIn("docs/qmd.md", (REPO / "README.md").read_text())


if __name__ == "__main__":
    unittest.main()
