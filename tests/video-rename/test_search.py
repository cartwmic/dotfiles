"""Black-box tests for `video-rename --search` (dot_local/bin/executable_video-rename).

The real script runs as a real process against a fake site on 127.0.0.1 (search pages, video pages, a login redirect)
and a temp folder of fake titled files, with HOME pointed at a temp dir so the undo log and the run log land there.
Everything is checked from outside: the printed lines, the exit code, the folder's file names, the requests the
fake site saw and the JSON lines the run wrote. No real site is involved.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("VIDEO_RENAME_SCRIPT") or ROOT / "dot_local/bin/executable_video-rename")

VIDEO_PAGES = {
    "101": "<title>An Example File Name | SiteName</title>",
    "401": "<title>Don&#39;t Stop: Go/Now | SiteName</title>",
    "501": "<title>Caf\u00e9 Nuit | SiteName</title>",
    "601": "<html>no title tag here</html>",
    "801": "<title>Other Place | SiteName</title>",
}

# lower-cased search words -> the links on the search page
SEARCH_LINKS = {
    # the same video linked twice (thumbnail and title; one absolute, one with a query string), and a different video
    # whose slug only starts with the title
    "an example file name": ["/video/101/an-example-file-name", "{base}/video/101/an-example-file-name?ref=thumb",
                             "/video/102/an-example-file-name-part-2"],
    "an example file name!": ["/video/101/an-example-file-name"],
    "ambiguous title": ["/video/201/ambiguous-title", "/video/202/ambiguous-title"],
    "nothing here": ["/video/301/something-else"],
    "dont stop": ["/video/401/don-t-stop"],
    "caf\u00e9 nuit": ["/video/501/cafe-nuit"],
    "no title page": ["/video/601/no-title-page"],
    "other place": ["/video/801/other-place"],
}

PASSWORD_FORM = '<html><form><input name="user"><input type="password" name="pw"></form></html>'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, time.monotonic()))
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query).get("q", [""])[0].lower()
        status, headers, body = 200, {}, ""
        if url.path == "/search":
            if query == "wall":
                status, headers = 302, {"Location": "/login?next=/search"}
            elif query == "forbidden":
                status, body = 403, "no"
            elif query == "password form":
                body = PASSWORD_FORM
            else:
                base = "http://127.0.0.1:%d" % self.server.server_port
                body = "<html>%s</html>" % "".join(
                    '<a href="%s">x</a>' % link.format(base=base) for link in SEARCH_LINKS.get(query, []))
        elif url.path == "/login":
            body = "<html>please sign in</html>"   # no password field: only the redirect gives the wall away
        elif url.path.startswith("/video/"):
            body = VIDEO_PAGES.get(url.path.split("/")[2])
            if body is None:
                status, body = 404, "missing"
        else:
            status, body = 404, "missing"
        data = body.encode()
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.server.requests = []
        cls.base = "http://127.0.0.1:%d" % cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.folder = Path(self.tmp.name) / "videos"
        self.folder.mkdir()
        self.server.requests.clear()

    def config(self, extra="", delay=0):
        path = self.home / "config.toml"
        path.write_text(
            f'search_template = "{self.base}/search?q={{query}}"\n'
            f"delay_seconds = {delay}\n"
            + r'strip = ["\\s*\\|\\s*SiteName$"]' + "\n" + extra)
        return path

    def touch(self, *names, folder=None):
        for n in names:
            ((folder or self.folder) / n).write_text("video bytes of " + n)

    def names(self, folder=None):
        return sorted(p.name for p in (folder or self.folder).iterdir())

    def search(self, *args, config=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--search", *args, "--config", str(config or self.config())],
            capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=60)

    def run_log(self):
        path = self.home / ".local/state/video-rename/search.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def undo_logs(self):
        return sorted((self.home / ".local/state/video-rename").glob("undo-*.jsonl"))

    # ---- the rename ----

    def test_dry_run_prints_old_to_new_and_changes_nothing(self):
        self.touch("An Example File Name.mp4")
        r = self.search(str(self.folder))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("An Example File Name.mp4 -> 101 - An Example File Name.mp4", r.stdout)
        self.assertIn("dry run; add --apply to rename", r.stdout)
        self.assertEqual(self.names(), ["An Example File Name.mp4"])
        self.assertEqual(self.undo_logs(), [])

    def test_apply_renames_and_undo_puts_the_name_back(self):
        self.touch("An Example File Name.mp4")
        r = self.search(str(self.folder), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["101 - An Example File Name.mp4"])
        self.assertEqual((self.folder / "101 - An Example File Name.mp4").read_text(), "video bytes of An Example File Name.mp4")
        undo = subprocess.run([sys.executable, str(SCRIPT), "--undo", str(self.undo_logs()[0])],
                              capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=60)
        self.assertEqual(undo.returncode, 0, undo.stderr)
        self.assertEqual(self.names(), ["An Example File Name.mp4"])

    def test_the_search_asks_for_the_file_title_and_a_video_linked_twice_counts_once(self):
        self.touch("An Example File Name.mp4")
        self.search(str(self.folder))
        paths = [p for p, _ in self.server.requests]
        self.assertEqual(paths[0], "/search?q=An+Example+File+Name")
        self.assertEqual(len(paths), 2)       # one search, one video page: the twice-linked video was not "more than one"
        self.assertTrue(paths[1].startswith("/video/101/an-example-file-name"))

    def test_the_title_is_made_safe_for_a_file_name(self):
        self.touch("dont stop.mp4")
        self.search(str(self.folder), "--apply")
        self.assertEqual(self.names(), ["401 - Don't Stop - Go-Now.mp4"])

    def test_accents_in_the_title_match_the_plain_slug(self):
        self.touch("caf\u00e9 nuit.mkv")
        self.search(str(self.folder), "--apply")
        self.assertEqual(self.names(), ["501 - Caf\u00e9 Nuit.mkv"])

    def test_an_existing_file_is_never_overwritten(self):
        self.touch("An Example File Name.mp4", "101 - An Example File Name.mp4")
        r = self.search(str(self.folder), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["101 - An Example File Name (2).mp4", "101 - An Example File Name.mp4"])
        self.assertEqual((self.folder / "101 - An Example File Name.mp4").read_text(), "video bytes of 101 - An Example File Name.mp4")

    def test_two_files_that_find_the_same_video_get_different_names(self):
        self.touch("An Example File Name.mp4", "An Example File Name!.mp4")
        r = self.search(str(self.folder), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["101 - An Example File Name (2).mp4", "101 - An Example File Name.mp4"])

    def test_a_name_that_already_has_an_id_is_left_alone_without_a_request(self):
        self.touch("101 - An Example File Name.mp4")
        r = self.search(str(self.folder), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 already named", r.stdout)
        self.assertEqual(self.server.requests, [])
        self.assertEqual(self.names(), ["101 - An Example File Name.mp4"])

    # ---- skipped files ----

    def test_no_match_more_than_one_match_and_no_title_are_skipped_and_listed(self):
        self.touch("ambiguous title.mp4", "nothing here.mp4", "no title page.mp4", "!!!.mp4", "never indexed.mp4")
        r = self.search(str(self.folder), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["!!!.mp4", "ambiguous title.mp4", "never indexed.mp4", "no title page.mp4", "nothing here.mp4"])
        self.assertIn("ambiguous title.mp4: 2 videos match this title (ids 201, 202)", r.stdout)
        self.assertIn("nothing here.mp4: no search result matches this title", r.stdout)
        self.assertIn("never indexed.mp4: no search result matches this title", r.stdout)
        self.assertIn("no title page.mp4: no title found on the page for id 601", r.stdout)
        self.assertIn("!!!.mp4: the name has no letters or digits to search for", r.stdout)
        self.assertIn("renamed 0, 5 skipped", r.stdout)
        self.assertNotIn("!!!", "".join(p for p, _ in self.server.requests))

    def test_one_skipped_file_does_not_stop_the_others(self):
        self.touch("nothing here.mp4", "An Example File Name.mp4")
        r = self.search(str(self.folder), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["101 - An Example File Name.mp4", "nothing here.mp4"])

    # ---- login wall ----

    def test_a_login_wall_stops_the_run_and_renames_nothing(self):
        walls = {"a redirect to a login page": "wall", "HTTP 403": "forbidden", "a password field": "password form"}
        for why, name in walls.items():
            with self.subTest(why):
                self.server.requests.clear()
                folder = Path(self.tmp.name) / ("f-" + name.replace(" ", "-"))
                folder.mkdir()
                # sorted order: "An Example File Name" would match, then the wall; a later file must not be asked for
                self.touch("An Example File Name.mp4", name + ".mp4", "zzz later.mp4", folder=folder)
                r = self.search(str(folder), "--apply")
                self.assertEqual(r.returncode, 1)
                self.assertIn("looks like a login wall", r.stderr)
                self.assertIn("Nothing was renamed", r.stderr)
                self.assertIn("headers_file", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(self.names(folder), sorted(["An Example File Name.mp4", name + ".mp4", "zzz later.mp4"]))
                self.assertFalse(any("zzz" in p for p, _ in self.server.requests))

    def test_the_login_wall_is_in_the_run_log(self):
        self.touch("wall.mp4")
        self.search(str(self.folder))
        outcomes = [(e["action"], e["outcome"]) for e in self.run_log()]
        self.assertEqual(outcomes, [("lookup", "login-wall"), ("run", "login-wall")])

    # ---- the polite delay ----

    def test_it_waits_between_every_request(self):
        self.touch("An Example File Name.mp4", "dont stop.mp4")
        r = self.search(str(self.folder), config=self.config(delay=0.3))
        self.assertEqual(r.returncode, 0, r.stderr)
        times = [t for _, t in self.server.requests]
        self.assertEqual(len(times), 4)    # a search and a video page for each file
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(all(g >= 0.25 for g in gaps), gaps)

    def test_the_delay_option_overrides_the_config(self):
        self.touch("An Example File Name.mp4")
        self.search(str(self.folder), "--delay", "0.3", config=self.config(delay=0))
        times = [t for _, t in self.server.requests]
        self.assertGreaterEqual(times[1] - times[0], 0.25)

    # ---- paths ----

    def test_it_takes_folders_and_files_together_and_shows_full_paths(self):
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        self.touch("An Example File Name.mp4", "unrelated.txt")
        self.touch("other place.mp4", folder=other)
        r = self.search(str(self.folder), str(other / "other place.mp4"), "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["101 - An Example File Name.mp4", "unrelated.txt"])
        self.assertEqual(self.names(other), ["801 - Other Place.mp4"])
        self.assertIn(f"{self.folder / 'An Example File Name.mp4'} -> {self.folder / '101 - An Example File Name.mp4'}", r.stdout)

    def test_a_file_given_by_path_is_the_only_one_looked_at(self):
        self.touch("An Example File Name.mp4", "dont stop.mp4")
        self.search(str(self.folder / "dont stop.mp4"), "--apply")
        self.assertEqual(self.names(), ["401 - Don't Stop - Go-Now.mp4", "An Example File Name.mp4"])

    def test_a_path_that_is_not_a_video_or_folder_fails_in_one_line(self):
        self.touch("notes.txt")
        for bad in (str(self.folder / "notes.txt"), str(self.folder / "missing.mp4")):
            r = self.search(bad)
            self.assertEqual(r.returncode, 1)
            self.assertIn("is not a video file or a folder", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_without_search_one_folder_is_still_required(self):
        r = subprocess.run([sys.executable, str(SCRIPT), str(self.folder), str(self.folder)],
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("give one FOLDER", r.stderr)

    def test_undo_takes_only_a_log_file(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--undo", "x.jsonl", "--search"],
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--undo takes only a log file", r.stderr)

    def test_help_describes_search(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(self.home)), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--search", r.stdout)
        self.assertIn("'<id> - <title>'", r.stdout)
        self.assertIn("a file or folders too with --search", r.stdout)

    # ---- config ----

    def test_search_needs_a_search_template_with_a_query_slot(self):
        for text in ('delay_seconds = 0\n', 'search_template = "http://127.0.0.1/search"\n'):
            cfg = self.home / "bad.toml"
            cfg.write_text(text)
            r = self.search(str(self.folder), config=cfg)
            self.assertEqual(r.returncode, 1)
            self.assertIn('config search_template must be a string containing "{query}"', r.stderr)

    def test_search_does_not_need_a_url_template(self):
        self.touch("An Example File Name.mp4")
        cfg = self.config()
        self.assertNotIn("url_template", cfg.read_text())
        self.assertEqual(self.search(str(self.folder), config=cfg).returncode, 0)

    def test_the_old_mode_still_needs_a_url_template(self):
        r = subprocess.run([sys.executable, str(SCRIPT), str(self.folder), "--config", str(self.config())],
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)), timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn('config url_template must be a string containing "{id}"', r.stderr)

    # ---- the run log ----

    def test_a_run_writes_one_json_line_per_step_tied_by_a_run_id(self):
        self.touch("An Example File Name.mp4", "nothing here.mp4", "101 - Done.mp4")
        r = self.search(str(self.folder))
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.run_log()
        self.assertEqual(len({e["run"] for e in log}), 1)
        self.assertEqual(sorted((e["action"], e["outcome"]) for e in log),
                         [("lookup", "already-named"), ("lookup", "matched"), ("lookup", "skipped"), ("run", "dry-run")])
        for e in log:
            self.assertRegex(e["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z$")
            self.assertIsInstance(e["ms"], int)
        matched = next(e for e in log if e["outcome"] == "matched")
        self.assertEqual((matched["file"], matched["id"], matched["new"]), ("An Example File Name.mp4", "101", "101 - An Example File Name.mp4"))
        skipped = next(e for e in log if e["outcome"] == "skipped")
        self.assertEqual(skipped["reason"], "no search result matches this title")
        done = next(e for e in log if e["action"] == "run")
        self.assertEqual((done["renames"], done["skipped"], done["already"]), (1, 1, 1))

    def test_an_applied_run_says_applied_and_two_runs_have_two_ids(self):
        self.touch("An Example File Name.mp4", "dont stop.mp4")
        self.search(str(self.folder / "An Example File Name.mp4"), "--apply")
        self.search(str(self.folder / "dont stop.mp4"))
        runs = [e for e in self.run_log() if e["action"] == "run"]
        self.assertEqual([e["outcome"] for e in runs], ["applied", "dry-run"])
        self.assertEqual(len({e["run"] for e in runs}), 2)


if __name__ == "__main__":
    unittest.main()
