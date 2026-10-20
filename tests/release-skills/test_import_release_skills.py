"""Black-box tests for dot_local/user_scripts/executable_import_release_skills.py.

Each test runs the real script as a subprocess against a throwaway chezmoi source tree, with a fake `gh` on PATH that serves
a small made-up release (a tag, its tree listing and its archive). Nothing here reaches GitHub, the real chezmoi source,
the real home directory or any deployed skill.

    python3 -m unittest discover -s tests/release-skills -v
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local" / "user_scripts" / "executable_import_release_skills.py"
SKILLS = Path("dot_local/share/agent-harness/canonical/skills")
COMMIT = "a" * 40
MOVED_COMMIT = "b" * 40

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_GH_STATE"]))
args = sys.argv[1:]
def out(value):
    sys.stdout.write(json.dumps(value))
    sys.exit(0)
def fail(message):
    sys.stderr.write(message + "\n")
    sys.exit(1)
if args[:2] == ["release", "view"]:
    release = state["releases"].get(args[2])
    if release is None:
        fail("release not found")
    out(release)
if args[0] == "api":
    path = args[1].split("?")[0]
    if "/git/ref/tags/" in path:
        ref = state["refs"].get(path.rsplit("/", 1)[1])
        out({"object": ref}) if ref else fail("no such ref")
    if "/git/tags/" in path:
        out({"object": state["tag_objects"][path.rsplit("/", 1)[1]]})
    if "/git/trees/" in path:
        out(state["trees"][path.rsplit("/", 1)[1]])
    if "/tarball/" in path:
        sys.stdout.buffer.write(open(state["tarballs"][path.rsplit("/", 1)[1]], "rb").read())
        sys.exit(0)
fail("fake gh: unexpected " + " ".join(args))
'''


def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


GOOD_TREE = {
    "skills/using-loop-engine/SKILL.md": b"root skill v1\n",
    "docs/agent-usage.md": b"agent usage v1\n",
    "docs/implementation-report-proof.md": b"irp\n",
    "docs/operational-ux-capture.schema.json": b"{}\n",
    "docs/operational-ux-contracts.md": b"ux\n",
    "docs/PRD.md": b"prd\n",
    "docs/not-a-reference.md": b"stays in the repo\n",
    "crates/foo-provider/README.md": b"foo readme\n",
    "crates/foo-provider/data/a.json": b"{\"a\":1}\n",
    "crates/foo-provider/data/deep/b.txt": b"b\n",
    "crates/foo-provider/docs/d.md": b"d\n",
    "crates/foo-provider/src/lib.rs": b"not a reference\n",
    "crates/foo-provider/skills/using-foo-provider/SKILL.md": b"foo skill v1\n",
    "crates/foo-provider/skills/using-other/SKILL.md": b"other skill\n",
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.source = self.dir / "source"
        (self.source / SKILLS).mkdir(parents=True)
        (self.source / "dot_config/mise").mkdir(parents=True)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.state_path = self.dir / "state.json"
        self.state = {"releases": {}, "refs": {}, "tag_objects": {}, "trees": {}, "tarballs": {}}
        self.release("v1.0.0", dict(GOOD_TREE))

    def release(self, tag, files, commit=COMMIT, modes=None, **release):
        """Serve a release: a tree listing with real blob hashes and an archive of the same files."""
        modes = modes or {}
        tree = [{"path": p, "type": "blob", "mode": modes.get(p, "100644"), "sha": blob_sha(d)} for p, d in files.items()]
        archive = self.dir / ("archive-%s.tgz" % commit)
        with tarfile.open(archive, "w:gz") as tar:
            for path, data in files.items():
                info = tarfile.TarInfo("owner-repo-%s/%s" % (commit[:7], path))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        self.state["releases"][tag] = {"tagName": tag, "isDraft": False, "isPrerelease": False, **release}
        self.state["refs"][tag] = {"type": "commit", "sha": commit}
        self.state["trees"][commit] = {"truncated": False, "tree": tree}
        self.state["tarballs"][commit] = str(archive)
        self.state_path.write_text(json.dumps(self.state))

    def run_tool(self, *argv, **env):
        merged = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE_GH_STATE": str(self.state_path),
                  "HOME": str(self.home), "AGENT_HARNESS_CANONICAL_ROOT": str(self.dir / "deployed"), **env}
        return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, env=merged, timeout=60)

    def do_import(self, *flags, tag="v1.0.0"):
        return self.run_tool("import", tag, "--source", str(self.source), *flags)

    def tree_state(self):
        base = self.source / SKILLS
        return {p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


class ImportTests(Fixture):
    def test_dry_run_reports_and_writes_nothing(self):
        result = self.do_import()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("commit " + COMMIT, result.stdout)
        self.assertIn("using-foo-provider", result.stdout)
        self.assertIn("dry run", result.stdout)
        self.assertEqual(self.tree_state(), {})

    def test_apply_writes_exactly_the_manifest_bytes(self):
        result = self.do_import("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {
            "using-loop-engine/SKILL.md": b"root skill v1\n",
            "using-loop-engine/references/agent-usage.md": b"agent usage v1\n",
            "using-loop-engine/references/implementation-report-proof.md": b"irp\n",
            "using-loop-engine/references/operational-ux-capture.schema.json": b"{}\n",
            "using-loop-engine/references/operational-ux-contracts.md": b"ux\n",
            "using-loop-engine/references/PRD.md": b"prd\n",
            "using-foo-provider/SKILL.md": b"foo skill v1\n",
            "using-foo-provider/references/README.md": b"foo readme\n",
            "using-foo-provider/references/data/a.json": b'{"a":1}\n',
            "using-foo-provider/references/data/deep/b.txt": b"b\n",
            "using-foo-provider/references/docs/d.md": b"d\n",
            "using-other/SKILL.md": b"other skill\n",  # a crate's references go to using-<crate> only
        }
        self.assertEqual(self.tree_state(), expected)
        again = self.do_import()
        self.assertIn("+0 added  ~0 changed  -0 orphan", again.stdout)
        self.assertEqual([l for l in again.stdout.splitlines() if l.startswith("    ")], [])  # no per-file change lines

    def test_update_changes_only_what_differs(self):
        self.do_import("--apply")
        files = dict(GOOD_TREE)
        files["crates/foo-provider/skills/using-foo-provider/SKILL.md"] = b"foo skill v2\n"
        files["crates/foo-provider/data/new.json"] = b"[]\n"
        self.release("v1.1.0", files, commit="c" * 40)
        dry = self.do_import(tag="v1.1.0")
        self.assertIn("change  using-foo-provider/SKILL.md", dry.stdout)
        self.assertIn("add     using-foo-provider/references/data/new.json", dry.stdout)
        self.assertEqual(self.tree_state()["using-foo-provider/SKILL.md"], b"foo skill v1\n")
        self.assertEqual(self.do_import("--apply", tag="v1.1.0").returncode, 0)
        state = self.tree_state()
        self.assertEqual(state["using-foo-provider/SKILL.md"], b"foo skill v2\n")
        self.assertEqual(state["using-foo-provider/references/data/new.json"], b"[]\n")

    def test_orphan_blocks_apply_until_pruned(self):
        self.do_import("--apply")
        orphan = self.source / SKILLS / "using-foo-provider/references/data/old.json"
        orphan.write_text("stale")
        (self.source / SKILLS / "using-foo-provider/SKILL.md").write_text("edited locally\n")
        before = self.tree_state()
        blocked = self.do_import("--apply")
        self.assertEqual(blocked.returncode, 3)
        self.assertIn("ORPHAN using-foo-provider/references/data/old.json", " ".join(blocked.stdout.split()))
        self.assertEqual(self.tree_state(), before)  # nothing written, not even the file that differs
        self.assertEqual(self.do_import("--apply", "--prune").returncode, 0)
        self.assertFalse(orphan.exists())
        self.assertEqual(self.tree_state()["using-foo-provider/SKILL.md"], b"foo skill v1\n")

    def test_other_bundles_are_never_touched(self):
        mine = self.source / SKILLS / "my-own-skill/SKILL.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("mine\n")
        self.do_import("--apply", "--prune")
        self.assertEqual(mine.read_text(), "mine\n")

    def test_annotated_tag_is_followed_to_its_commit(self):
        self.state["refs"]["v1.0.0"] = {"type": "tag", "sha": "d" * 40}
        self.state["tag_objects"]["d" * 40] = {"type": "commit", "sha": COMMIT}
        self.state_path.write_text(json.dumps(self.state))
        self.assertIn("commit " + COMMIT, self.do_import().stdout)

    def test_a_moved_tag_is_refused(self):
        self.assertEqual(self.do_import("--expect-commit", COMMIT[:12]).returncode, 0)
        self.state["refs"]["v1.0.0"] = {"type": "commit", "sha": MOVED_COMMIT}
        self.release("v1.0.0", dict(GOOD_TREE), commit=MOVED_COMMIT)
        result = self.do_import("--apply", "--expect-commit", COMMIT[:12])
        self.assertEqual(result.returncode, 1)
        self.assertIn("moved", result.stderr)
        self.assertEqual(self.tree_state(), {})

    def test_unpublished_or_unknown_tags_are_refused(self):
        self.release("v2.0.0-rc.1", dict(GOOD_TREE), commit="e" * 40, isPrerelease=True)
        self.release("v3.0.0", dict(GOOD_TREE), commit="f" * 40, isDraft=True)
        for tag in ("v2.0.0-rc.1", "v3.0.0", "v9.9.9"):
            with self.subTest(tag=tag):
                result = self.do_import("--apply", tag=tag)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.tree_state(), {})

    def test_an_archive_that_differs_from_the_tree_is_refused(self):
        files = dict(GOOD_TREE)
        self.release("v1.0.0", files)
        tampered = dict(files, **{"crates/foo-provider/data/a.json": b'{"a":2}\n'})
        archive = self.dir / "tampered.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            for path, data in tampered.items():
                info = tarfile.TarInfo("owner-repo-%s/%s" % (COMMIT[:7], path))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        self.state["tarballs"][COMMIT] = str(archive)
        self.state_path.write_text(json.dumps(self.state))
        result = self.do_import("--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("blob hash", result.stderr)
        self.assertEqual(self.tree_state(), {})

    def test_an_archive_of_another_commit_is_refused(self):
        archive = self.dir / "other.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            for path, data in GOOD_TREE.items():
                info = tarfile.TarInfo("owner-repo-%s/%s" % (MOVED_COMMIT[:7], path))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        self.state["tarballs"][COMMIT] = str(archive)
        self.state_path.write_text(json.dumps(self.state))
        result = self.do_import("--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not commit", result.stderr)
        self.assertEqual(self.tree_state(), {})

    def test_unsafe_files_in_a_bundle_are_refused(self):
        cases = {
            "symlink": ({"crates/foo-provider/data/link": b"a.json"}, {"crates/foo-provider/data/link": "120000"}, "mode"),
            "chezmoi attribute": ({"crates/foo-provider/data/dot_hidden": b"x\n"}, {}, "chezmoi"),
            "template": ({"crates/foo-provider/data/x.tmpl": b"x\n"}, {}, "chezmoi"),
            "empty": ({"crates/foo-provider/data/empty.txt": b""}, {}, "empty"),
        }
        for label, (extra, modes, message) in cases.items():
            with self.subTest(label):
                self.release("v1.0.0", {**GOOD_TREE, **extra}, modes=modes)
                result = self.do_import("--apply")
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.tree_state(), {})

    def test_an_executable_bit_in_the_tag_is_dropped_not_refused(self):
        self.release("v1.0.0", dict(GOOD_TREE), modes={"crates/foo-provider/data/a.json": "100755"})
        self.assertEqual(self.do_import("--apply").returncode, 0)

    def test_a_missing_root_reference_doc_is_refused(self):
        files = dict(GOOD_TREE)
        del files["docs/PRD.md"]
        self.release("v1.0.0", files)
        result = self.do_import("--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/PRD.md", result.stderr)

    def test_no_bundles_in_the_tag_is_an_error(self):
        self.release("v1.0.0", {"README.md": b"x\n"})
        self.assertEqual(self.do_import().returncode, 1)

    def test_pins_move_with_the_import_and_only_the_four_tool_lines(self):
        config = self.source / "dot_config/mise/config.toml"
        original = (
            'gh = "latest"\n'
            'loop-engine = { version = "0.9.0", matching_regex = "^loop-cli-", rename_exe = "loop-engine" }\n'
            'software-change = { version = "0.9.0", matching_regex = "^software-change-provider-", rename_exe = "software-change" }\n'
            'policy-document = { version = "0.9.0", matching_regex = "^policy-document-provider-", rename_exe = "policy-document" }\n'
            'research = { version = "0.9.0", matching_regex = "^research-provider-", rename_exe = "research" }\n'
            'other = { version = "0.9.0" }\n'
        )
        config.write_text(original)
        self.assertEqual(self.do_import("--apply").returncode, 0)
        self.assertEqual(config.read_text(), original)  # no --pins, no pin change
        self.assertEqual(self.do_import("--pins", "--apply", "--prune").returncode, 0)
        self.assertEqual(config.read_text(), original.replace('version = "0.9.0", matching', 'version = "1.0.0", matching'))
        self.assertIn('other = { version = "0.9.0" }', config.read_text())

    def test_pins_refuse_a_config_that_does_not_have_the_four_lines(self):
        (self.source / "dot_config/mise/config.toml").write_text('gh = "latest"\n')
        result = self.do_import("--pins", "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.tree_state(), {})


class VerifyDeployedTests(Fixture):
    def setUp(self):
        super().setUp()
        self.do_import("--apply")
        self.deployed = self.dir / "deployed" / "skills"
        for name in ("using-loop-engine", "using-foo-provider", "using-other"):
            for path in (self.source / SKILLS / name).rglob("*"):
                if path.is_file():
                    target = self.deployed / path.relative_to(self.source / SKILLS)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(path.read_bytes())
            for harness in (".claude/skills", ".codex/skills", ".pi/agent/skills"):
                link = self.home / harness / name
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(self.deployed / name)

    def verify(self, *names):
        return self.run_tool("verify-deployed", *names, "--source", str(self.source))

    def test_matching_deployment_and_links_pass(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("3 bundle(s) checked, 0 problem(s)", result.stdout)

    def test_changed_missing_and_orphan_deployed_files_fail(self):
        (self.deployed / "using-foo-provider/SKILL.md").write_text("drift\n")
        (self.deployed / "using-foo-provider/references/README.md").unlink()
        (self.deployed / "using-foo-provider/references/data/old.json").write_text("stale")
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("differs in the deployment: SKILL.md", result.stdout)
        self.assertIn("missing from the deployment: references/README.md", result.stdout)
        self.assertIn("ORPHAN in the deployment (apply does not delete it): references/data/old.json", result.stdout)

    def test_a_missing_or_wrong_harness_link_fails(self):
        (self.home / ".claude/skills/using-other").unlink()
        wrong = self.home / ".codex/skills/using-other"
        wrong.unlink()
        wrong.symlink_to(self.deployed / "using-foo-provider")
        result = self.verify("using-other")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no link at", result.stdout)
        self.assertIn("does not link to", result.stdout)

    def test_a_bundle_that_is_not_deployed_fails(self):
        import shutil
        shutil.rmtree(self.deployed / "using-other")
        result = self.verify("using-other")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not deployed", result.stdout)

    def test_an_unknown_name_fails(self):
        self.assertEqual(self.verify("nope").returncode, 1)

    def test_a_chezmoi_executable_prefix_is_not_part_of_the_deployed_name(self):
        source_file = self.source / SKILLS / "using-other/executable_run.sh"
        source_file.write_text("#!/bin/sh\n")
        (self.deployed / "using-other/run.sh").write_text("#!/bin/sh\n")
        self.assertEqual(self.verify("using-other").returncode, 0)


if __name__ == "__main__":
    unittest.main()
