"""The daily `qmd cleanup` inside qmd-refresh (docs/qmd.md "Daily cleanup").

Behaviour: the real qmd-refresh runs against the fake qmd and heavy-gate of test_refresh (scratch dirs only, no real qmd or index).
Static: the switch (chezmoi data qmd.refresh.cleanup) renders from the real source with a throwaway config and HOME.
"""
import os
import sqlite3
import time
import unittest

from test_refresh import Base, until
from test_schedule import Chezmoi, render, REPO, DOC

CONF = REPO / "dot_config/qmd/refresh.conf.tmpl"
DAY = 86400


class CleanupTest(Base):
    def setUp(self):
        self.e = self.make(cleanup=True)   # no refresh.conf: the default, on
        self.notes = self.e.root / "notes"
        self.notes.mkdir()
        self.index_with(self.e, [("notes", self.notes, 1)])

    @staticmethod
    def index_with(e, collections, schema=True):
        """A qmd index as far as the cleanup guard reads it: store_collections (what qmd update globs) and documents.
        collections: (name, folder, active) with active 1 (one active document), 0 (only an inactive one) or None (none)."""
        e.index.parent.mkdir(parents=True, exist_ok=True)
        if e.index.exists():
            e.index.unlink()
        db = sqlite3.connect(str(e.index))
        db.execute("create table content_vectors (hash text, seq integer, embedded_at text)")
        if schema:
            db.execute("create table store_collections (name text primary key, path text not null)")
            db.execute("create table documents (id integer primary key, collection text, path text, hash text, active integer)")
            for name, folder, active in collections:
                db.execute("insert into store_collections values (?, ?)", (name, str(folder)))
                if active is not None:
                    db.execute("insert into documents (collection, path, hash, active) values (?, 'a.md', 'h', ?)", (name, active))
        db.commit()
        db.close()

    @property
    def cstamp(self):
        return self.e.state / "qmd-refresh" / "last-cleanup"

    def conf(self, text):
        d = self.e.root / "config" / "qmd"
        d.mkdir(parents=True, exist_ok=True)
        (d / "refresh.conf").write_text(text)

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

    def test_a_bad_refresh_conf_runs_nothing(self):
        # Fail closed: an existing file must say exactly cleanup=on or cleanup=off, once. Only a missing file means on.
        for text in ("cleanup=yes\n", "cleanup=false\n", "cleanup=On\n", "cleanup= off\n", "cleanup=off \n", "cleanup=\n",
                     "cleanup =off\n", " cleanup=off\n", "cleanup=off\ncleanup=on\n", "cleanup=yes\ncleanup=off\n",
                     "cleanup=off\nother=1\n", "", "# only a comment\n\n", "cleanup=off\r\n"):
            self.conf(text)
            self.assertEqual(self.e.run(), 2, repr(text))
            self.assertIn("expected one line, cleanup=on or cleanup=off", self.e.err, repr(text))
            self.assertEqual(self.e.run("status"), 2, repr(text))
        self.assertEqual(self.e.calls, [])

    def test_an_unreadable_refresh_conf_runs_nothing(self):
        self.conf("cleanup=on\n")
        f = self.e.root / "config" / "qmd" / "refresh.conf"
        f.chmod(0)
        self.addCleanup(f.chmod, 0o644)
        if os.access(f, os.R_OK):
            self.skipTest("running as root")
        self.assertEqual(self.e.run(), 2)
        self.assertEqual(self.e.calls, [])

    def test_the_rendered_file_is_read(self):
        for want, data in (("off", "qmd: {refresh: {cleanup: false}}"), ("on", "")):
            r, _ = render(CONF, data=data)
            self.conf(r.stdout)
            n = len(self.cleanups)
            self.stamp_age(DAY + 1)
            self.assertEqual(self.e.run(), 0, self.e.err)
            self.assertEqual(len(self.cleanups), n + (want == "on"), want)

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
        # The folders come from the index (store_collections, what qmd update globbed), whatever YAML style index.yml uses.
        gone = self.e.root / "Volumes" / "Work shop" / "repo"
        self.index_with(self.e, [("notes", self.notes, 1), ("repo", gone, 1)])
        cfg = self.e.root / "config" / "qmd"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "index.yml").write_text('collections: {notes: {"path": "%s"}}\n' % self.notes)   # not consulted
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(self.cleanups, [])
        self.assertIn("qmd cleanup skipped: collection folder %s is missing" % gone, self.e.err)
        self.assertFalse(self.cstamp.exists())
        gone.mkdir(parents=True)
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(len(self.cleanups), 1)

    def test_the_users_sqliterc_does_not_change_what_the_guard_reads(self):
        # sqlite3 reads a startup file ($XDG_CONFIG_HOME/sqlite3/sqliterc, or ~/.sqliterc); headers or column mode would turn
        # "path" or padding into a missing folder, every day.
        rc = ".headers on\n.mode column\n"
        (self.e.home / ".sqliterc").write_text(rc)
        (self.e.root / "config" / "sqlite3").mkdir(parents=True, exist_ok=True)
        (self.e.root / "config" / "sqlite3" / "sqliterc").write_text(rc)
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertNotIn("skipped", self.e.err)
        self.assertEqual(len(self.cleanups), 1)
        self.assertEqual(self.e.run("status"), 0)
        self.assertNotIn("may predate", self.e.out, "the vector count is read the same way")

    def test_a_collection_left_with_only_inactive_documents_holds_the_cleanup(self):
        # The folder exists but is empty (an empty mount point): update deactivated every document of the collection.
        empty = self.e.root / "mnt"
        empty.mkdir()
        self.index_with(self.e, [("notes", self.notes, 1), ("disk", empty, 0)])
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(self.cleanups, [])
        self.assertIn("qmd cleanup skipped: collection disk has no active document left", self.e.err)
        # A collection that never had documents, or still has an active one next to removed files, is fine.
        self.index_with(self.e, [("notes", self.notes, 1), ("disk", empty, None)])
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(len(self.cleanups), 1)

    def test_an_index_it_cannot_read_holds_the_cleanup(self):
        for setup in ("no index", "no collection table", "no collections"):
            e = self.make(cleanup=True)
            if setup == "no collection table":
                self.index_with(e, [], schema=False)
            elif setup == "no collections":
                self.index_with(e, [])
            self.assertEqual(e.run(), 0, e.err)
            self.assertEqual([c for c in e.qmd_calls if c.startswith("qmd cleanup")], [], setup)
            self.assertIn("qmd cleanup skipped: cannot read the collection folders", e.err, setup)
            self.assertFalse((e.state / "qmd-refresh" / "last-cleanup").exists(), setup)
            self.assertFalse(e.index.exists() if setup == "no index" else False, "the check must not create an index")

    def test_runs_without_the_embedding_model_or_with_no_embed(self):
        e = self.make(model=False, cleanup=True)
        self.index_with(e, [("notes", self.notes, 1)])
        self.assertEqual(e.run(), 0, e.err)
        self.assertEqual([c.split(" |")[0] for c in e.qmd_calls], ["qmd update", "qmd cleanup"])
        self.assertIn("update (embed skipped: model not on disk) + cleanup", e.stamp.read_text())
        e2 = self.make(cleanup=True)
        self.index_with(e2, [("notes", self.notes, 1)])
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
