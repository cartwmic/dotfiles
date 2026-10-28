"""The daily `qmd cleanup` inside qmd-refresh (docs/qmd.md "Daily cleanup").

Behaviour: the real qmd-refresh runs against the fake qmd and heavy-gate of test_refresh (scratch dirs only, no real qmd or index).
Static: the switch (chezmoi data qmd.refresh.cleanup) renders from the real source with a throwaway config and HOME.
"""
import os
import time
import unittest

from test_refresh import Base, until
from test_schedule import Chezmoi, render, REPO, DOC

CONF = REPO / "dot_config/qmd/refresh.conf.tmpl"
DAY = 86400


class CleanupTest(Base):
    def setUp(self):
        self.e = self.make(cleanup=True)   # no refresh.conf: the default, on

    @property
    def cstamp(self):
        return self.e.state / "qmd-refresh" / "last-cleanup"

    def conf(self, text):
        d = self.e.root / "config" / "qmd"
        d.mkdir(parents=True, exist_ok=True)
        (d / "refresh.conf").write_text(text)

    def index_yml(self, *paths):
        d = self.e.root / "config" / "qmd"
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.yml").write_text("collections:\n" + "".join("  c%d:\n    path: %s\n    pattern: \"**/*.md\"\n" % (i, p) for i, p in enumerate(paths)))

    def stamp_age(self, secs):
        self.cstamp.parent.mkdir(parents=True, exist_ok=True)
        self.cstamp.write_text("%d 2020-01-01T00:00:00Z\n" % (time.time() - secs))

    @property
    def cleanups(self):
        return [c for c in self.e.qmd_calls if c.startswith("qmd cleanup")]

    def test_first_run_ends_the_same_gate_job_with_a_plain_cleanup(self):
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(len([c for c in self.e.calls if c.startswith("heavy-gate")]), 1, "one gate job, no second gate")
        self.assertEqual([c.split(" |")[0] for c in self.e.qmd_calls],
                         ["qmd update", "qmd embed --timeout 0 --max-docs-per-batch 50 --max-batch-mb 8", "qmd cleanup"])
        self.assertEqual((self.e.fake / "nice").read_text().split(), ["nice=10"])
        self.assertRegex(self.cstamp.read_text(), r"^\d+ \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n$")
        self.assertRegex(self.e.stamp.read_text(), r"ok: update \+ embed \+ cleanup\n$")
        self.assertIn("done: update + embed + cleanup", self.e.err)

    def test_never_more_than_once_per_24_hours(self):
        self.assertEqual(self.e.run(), 0)
        self.assertEqual(self.e.run(), 0)
        self.assertEqual(len(self.cleanups), 1)
        self.assertRegex(self.e.stamp.read_text(), r"ok: update \+ embed\n$", "a run that did not clean says so")
        self.assertNotIn("cleanup", self.e.err, "skipping because it ran today is quiet")
        self.stamp_age(DAY - 600)
        self.assertEqual(self.e.run(), 0)
        self.assertEqual(len(self.cleanups), 1)
        self.stamp_age(DAY + 1)
        self.assertEqual(self.e.run(), 0)
        self.assertEqual(len(self.cleanups), 2)

    def test_an_unreadable_stamp_counts_as_never(self):
        for text in ("", "garbage\n", "-5 x\n", "%d 2100-01-01T00:00:00Z\n" % (time.time() + 365 * DAY)):
            self.cstamp.parent.mkdir(parents=True, exist_ok=True)
            self.cstamp.write_text(text)
            n = len(self.cleanups)
            self.assertEqual(self.e.run(), 0, self.e.err)
            self.assertEqual(len(self.cleanups), n + 1, repr(text))

    def test_off_in_refresh_conf(self):
        self.conf("# comment\ncleanup=off\n")
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(self.cleanups, [])
        self.assertFalse(self.cstamp.exists())
        self.assertEqual(self.e.run("status"), 0)
        self.assertIn("cleanup: off", self.e.out)
        self.assertEqual(self.e.run("--dry-run"), 0)
        self.assertIn("cleanup: off", self.e.out)

    def test_on_in_refresh_conf_and_a_missing_file_mean_on(self):
        self.conf("cleanup=on\n")
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(len(self.cleanups), 1)

    def test_a_bad_value_in_refresh_conf_runs_nothing(self):
        for v in ("yes", "false", "On", " off"):
            self.conf("cleanup=%s\n" % v)
            self.assertEqual(self.e.run(), 2, v)
            self.assertIn("cleanup must be on or off", self.e.err)
        self.assertEqual(self.e.calls, [])

    def test_no_cleanup_flag_skips_it_for_one_run(self):
        self.assertEqual(self.e.run("--no-cleanup"), 0)
        self.assertEqual(self.cleanups, [])
        self.assertEqual(self.e.run(), 0)
        self.assertEqual(len(self.cleanups), 1)

    def test_a_failed_cleanup_does_not_fail_the_refresh_and_is_retried(self):
        self.assertEqual(self.e.run_with("cleanup", 4), 0, self.e.err)
        self.assertIn("qmd cleanup failed (status 4)", self.e.err)
        self.assertFalse(self.cstamp.exists())
        self.assertRegex(self.e.stamp.read_text(), r"ok: update \+ embed\n$")
        self.assertEqual(self.e.run(), 0)
        self.assertEqual(len(self.cleanups), 2)
        self.assertTrue(self.cstamp.exists())

    def test_no_cleanup_after_a_failed_update_or_embed(self):
        for cmd in ("update", "embed"):
            self.assertEqual(self.e.run_with(cmd, 3), 3, cmd)
        self.assertEqual(self.cleanups, [])
        self.assertFalse(self.cstamp.exists())

    def test_a_missing_collection_folder_holds_the_cleanup(self):
        # An unmounted disk: update deactivates that collection's documents, and cleanup would then drop their vectors.
        here = self.e.root / "notes"
        here.mkdir()
        gone = self.e.root / "Volumes" / "Workshop" / "repo"
        self.index_yml(here, gone)
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(self.cleanups, [])
        self.assertIn("qmd cleanup skipped: collection folder %s is missing" % gone, self.e.err)
        self.assertFalse(self.cstamp.exists())
        gone.mkdir(parents=True)
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(len(self.cleanups), 1)

    def test_runs_without_the_embedding_model_or_with_no_embed(self):
        e = self.make(model=False, cleanup=True)
        self.assertEqual(e.run(), 0, e.err)
        self.assertEqual([c.split(" |")[0] for c in e.qmd_calls], ["qmd update", "qmd cleanup"])
        self.assertIn("update (embed skipped: model not on disk) + cleanup", e.stamp.read_text())
        e2 = self.make(cleanup=True)
        self.assertEqual(e2.run("--no-embed"), 0, e2.err)
        self.assertEqual([c.split(" |")[0] for c in e2.qmd_calls], ["qmd update", "qmd cleanup"])

    def test_reembed_is_never_added(self):
        self.assertEqual(self.e.run(), 0)
        self.stamp_age(DAY + 1)
        self.assertEqual(self.e.run(), 0)
        self.assertFalse([c for c in self.e.qmd_calls if " -f " in c + " "], "plain refreshes never force a re-embed")
        self.assertEqual({c.split(" |")[0] for c in self.cleanups}, {"qmd cleanup"}, "no flags, never --dry-run or anything else")

    def test_held_lock_exits_75_and_does_not_clean(self):
        p = self.e.popen(FAKE_QMD_SLEEP="update", FAKE_QMD_SECS="30")
        self.assertIsNotNone(self.e.qmd_pid())
        self.assertEqual(self.e.run(), 75)
        self.assertEqual(self.cleanups, [])
        p.terminate()
        p.communicate(timeout=30)
        self.assertEqual(self.cleanups, [], "a stopped job does not clean either")

    def test_status_and_dry_run(self):
        self.assertEqual(self.e.run("status"), 0)
        self.assertIn("cleanup: not run yet", self.e.out)
        self.assertEqual(self.e.run("--dry-run"), 0)
        self.assertIn("cleanup: %s cleanup (at most once per 24 h, last: never" % (self.e.bin / "qmd"), self.e.out)
        self.assertEqual(self.e.calls, [])
        self.assertEqual(self.e.run(), 0)
        self.assertEqual(self.e.run("status"), 0)
        self.assertRegex(self.e.out, r"cleanup: last \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


class SwitchTest(unittest.TestCase):
    def test_default_is_on(self):
        r, _ = render(CONF)
        self.assertIn("\ncleanup=on\n", r.stdout)
        r2, _ = render(CONF, data="qmd: {refresh: {cleanup: true}}")
        self.assertEqual(r.stdout, r2.stdout)

    def test_false_renders_off_and_is_independent_of_the_schedule(self):
        r, _ = render(CONF, data="qmd: {refresh: {cleanup: false}}")
        self.assertIn("\ncleanup=off\n", r.stdout)
        r, _ = render(CONF, data="qmd: {refresh: {enabled: false}}")
        self.assertIn("\ncleanup=on\n", r.stdout, "hand-run refreshes still clean when the schedule is off")

    def test_a_bad_value_fails_the_render(self):
        for v in ('"yes"', "1", "off", '"false "'):
            r, _ = render(CONF, data="qmd: {refresh: {cleanup: %s}}" % v, check=False)
            self.assertNotEqual(r.returncode, 0, v)
            self.assertIn("qmd.refresh.cleanup must be true or false", r.stderr, v)

    def test_lands_where_qmd_refresh_reads_it_on_personal_and_work_only(self):
        for profile, want in (("personal", True), ("axon-work-computer", True), ("termux", False)):
            c = Chezmoi(profile)
            try:
                m = c.run("managed").stdout.split()
            finally:
                c.close()
            self.assertEqual(".config/qmd/refresh.conf" in m, want, profile)


class DocTest(unittest.TestCase):
    def test_documented(self):
        t = DOC.read_text()
        self.assertIn("## Daily cleanup", t)
        self.assertIn("qmd.refresh.cleanup", t)
        self.assertIn("--no-cleanup", t)
        self.assertIn("refresh.conf", t)


if __name__ == "__main__":
    unittest.main()
