"""The chezmoi step that writes kgate's cluster and profile files from the machine's own chezmoi data (run_onchange_after_45_kgate_cluster_files.sh.tmpl).

Renders the real template with `chezmoi execute-template` against a throwaway config, then runs the rendered script with a throwaway HOME.
The data here is invented; the repo holds the mechanism only.
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "run_onchange_after_45_kgate_cluster_files.sh.tmpl"
CLUSTER = 'kind = "kubectl"\nkubeconfig = "~/.kube/example"\ncontext = "example-ctx"\nnamespace = "jobs"\n'
PROFILE = 'cluster = "example"\nimage = "registry.example/ci/runner:1@sha256:' + "ab" * 32 + '"\ncpu = 2\n'


class ClusterFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kc-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()

    def render(self, data_yaml, profile="personal"):
        cfg = self.tmp / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n%s" % (profile, data_yaml))
        return subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "--destination", str(self.home),
                               "execute-template"], input=TEMPLATE.read_text(), capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=60)

    def run_script(self, script):
        path = self.tmp / "script.sh"
        path.write_text(script)
        return subprocess.run(["sh", str(path)], capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=30)

    def data(self, clusters=None, profiles=None):
        def block(name, items):
            return "    %s:\n%s" % (name, "".join("      %s: |\n%s" % (k, "".join("        %s\n" % l for l in v.splitlines())) for k, v in items.items()))
        return "  kgate:\n" + (block("clusters", clusters) if clusters else "") + (block("profiles", profiles) if profiles else "")

    def files(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*") if p.is_file())

    def test_no_kgate_data_renders_nothing_and_writes_nothing(self):
        done = self.render("")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, ""), done.stderr)
        self.assertEqual(self.files(), [])

    def test_empty_maps_render_nothing(self):
        for data in ("  kgate:\n", "  kgate: {}\n", "  kgate:\n    clusters: {}\n    profiles: {}\n"):
            with self.subTest(data):
                done = self.render(data)
                self.assertEqual((done.returncode, done.stdout.strip()), (0, ""), done.stderr)

    def test_data_writes_the_cluster_and_profile_files_with_their_exact_text_mode_600(self):
        done = self.render(self.data({"example": CLUSTER, "second": CLUSTER.replace("jobs", "other")}, {"example-job": PROFILE}))
        self.assertEqual(done.returncode, 0, done.stderr)
        ran = self.run_script(done.stdout)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(self.files(), [".config/kgate/clusters/example.toml", ".config/kgate/clusters/second.toml", ".config/kgate/profiles/example-job.toml"])
        base = self.home / ".config" / "kgate"
        self.assertEqual((base / "clusters" / "example.toml").read_text(), CLUSTER)
        self.assertEqual((base / "clusters" / "second.toml").read_text(), CLUSTER.replace("jobs", "other"))
        self.assertEqual((base / "profiles" / "example-job.toml").read_text(), PROFILE)
        self.assertEqual(stat.S_IMODE((base / "clusters" / "example.toml").stat().st_mode), 0o600)

    def test_text_with_quotes_backslashes_and_dollar_signs_survives(self):
        tricky = 'a = "x\\\\y"\nb = \'$HOME `id` "quoted"\'\n'
        done = self.render(self.data({"example": tricky}))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.run_script(done.stdout).returncode, 0)
        self.assertEqual((self.home / ".config" / "kgate" / "clusters" / "example.toml").read_text(), tricky)

    def test_changed_data_rewrites_the_file(self):
        for text in (CLUSTER, CLUSTER.replace("jobs", "changed")):
            done = self.render(self.data({"example": text}))
            self.assertEqual(self.run_script(done.stdout).returncode, 0)
            self.assertEqual((self.home / ".config" / "kgate" / "clusters" / "example.toml").read_text(), text)

    def test_any_profile_with_data_gets_the_files(self):
        for profile in ("personal", "axon-work-computer", "termux"):
            with self.subTest(profile):
                done = self.render(self.data({"example": CLUSTER}), profile=profile)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertIn("write clusters", done.stdout)

    def test_a_name_that_is_not_a_plain_file_name_fails_the_render(self):
        for name in ("../escape", "a/b", ".hidden"):
            with self.subTest(name):
                done = self.render('  kgate:\n    clusters:\n      "%s": "x = 1"\n' % name)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("not a plain file name", done.stderr)

    def test_a_value_that_is_not_text_fails_the_render(self):
        done = self.render('  kgate:\n    profiles:\n      example-job: {cluster: example}\n')
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("must be TOML text", done.stderr)


if __name__ == "__main__":
    unittest.main()
