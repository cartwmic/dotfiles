"""Black-box tests for dot_local/bin/executable_video-rename.

The real script runs as a real process against a fake HTTP server (HTML and JSON pages on 127.0.0.1) and a temp
folder of fake numbered files, with HOME pointed at a temp dir so the undo log lands there. Everything is checked
from outside: the printed lines, the exit code, the folder's file names and the undo log's effect.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("VIDEO_RENAME_SCRIPT") or ROOT / "dot_local/bin/executable_video-rename")

# path -> (status, content type, body)
PAGES = {
    "/page/1": (200, "text/html", "<html><head><title>First &amp; Best | SiteName</title></head></html>"),
    "/page/2": (200, "text/html", "<title>Second: part/one</title>"),
    "/page/3": (200, "text/html", "<title>Same Title | SiteName</title>"),
    "/page/4": (200, "text/html", "<title>Same Title | SiteName</title>"),
    "/page/5": (200, "text/html", "<html>no title tag here</html>"),
    "/page/6": (200, "text/html", "<title>   </title>"),
    "/page/7": (200, "text/html", "<title>Taken | SiteName</title>"),
    "/api/1": (200, "application/json", json.dumps({"data": {"title": "Json One"}, "items": [{"name": "Json One"}]})),
    "/api/2": (200, "application/json", json.dumps({"data": {}})),
    "/api/3": (200, "application/json", "not json"),
    "/rx/1": (200, "text/html", "<h1 class='t'>Regex One</h1>"),
    "/page/9": (200, "text/html", "<title>%s</title>" % ("é" * 300)),
    "/page/10": (200, "text/html", "<title>Early</title>"),
    "/page/11": (200, "text/html", "<title>Late</title>"),
    "/page/12": (200, "text/html", "<title>Other</title>"),
    "/page/13": (200, "text/html", "<title>Caf\u00e9</title>"),
    "/page/14": (200, "text/html", "<title>1984</title>"),
    "/page/1984": (200, "text/html", "<title>Other Video</title>"),
    "/rx/2": (200, "text/html", "<h1 class='t'>Don&#39;t Stop &amp; Go</h1>"),
    "/api/4": (200, "application/json", json.dumps({"data": {"title": "Fish &amp; Chips"}})),
    "/cookie/1": (200, "text/html", "<title>Cookie Title</title>"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, dict(self.headers)))
        if self.path in self.server.hooks:
            self.server.hooks[self.path]()   # a test's side effect on the disk while the script is running
        if self.path.startswith("/cookie/") and self.headers.get("Cookie") != "session=abc":
            status, ctype, body = 403, "text/html", "forbidden"
        else:
            status, ctype, body = PAGES.get(self.path, (404, "text/html", "missing"))
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class VideoRenameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.server.requests = []
        cls.server.hooks = {}
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
        self.server.hooks.clear()

    def write_config(self, text, name="config.toml"):
        path = self.home / name
        path.write_text(text)
        return path

    def html_config(self, extra=""):
        return self.write_config(f'url_template = "{self.base}/page/{{id}}"\ndelay_seconds = 0\n{extra}')

    def touch(self, *names):
        for n in names:
            (self.folder / n).write_text("video bytes of " + n)

    def names(self):
        return sorted(p.name for p in self.folder.iterdir())

    def run_cli(self, *args, config=None):
        args = list(args)
        if config is not None and "--undo" not in args:
            args += ["--config", str(config)]
        return subprocess.run([sys.executable, str(SCRIPT)] + args, capture_output=True, text=True,
                              env=dict(os.environ, HOME=str(self.home)), timeout=60)

    def undo_logs(self):
        return sorted((self.home / ".local/state/video-rename").glob("undo-*.jsonl"))

    # ---- dry run ----

    def test_dry_run_prints_old_to_new_and_changes_nothing(self):
        cfg = self.html_config(r'strip = ["\\s*\\|\\s*SiteName$"]')
        self.touch("1.mp4", "2.mkv")
        r = self.run_cli(str(self.folder), config=cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1.mp4 -> First & Best.mp4", r.stdout)
        self.assertIn("2.mkv -> Second - part-one.mkv", r.stdout)   # / and : cannot be in a macOS name
        self.assertEqual(self.names(), ["1.mp4", "2.mkv"])
        self.assertEqual(self.undo_logs(), [])

    # ---- apply and undo ----

    def test_apply_renames_and_undo_restores_everything(self):
        cfg = self.html_config(r'strip = ["\\s*\\|\\s*SiteName$"]')
        self.touch("1.mp4", "2.mkv", "notes.txt")
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["First & Best.mp4", "Second - part-one.mkv", "notes.txt"])
        self.assertEqual((self.folder / "First & Best.mp4").read_text(), "video bytes of 1.mp4")   # same file, new name
        logs = self.undo_logs()
        self.assertEqual(len(logs), 1)
        self.assertIn(str(logs[0]), r.stdout)

        u = self.run_cli("--undo", str(logs[0]))
        self.assertEqual(u.returncode, 0, u.stderr)
        self.assertEqual(self.names(), ["1.mp4", "2.mkv", "notes.txt"])
        self.assertEqual((self.folder / "2.mkv").read_text(), "video bytes of 2.mkv")

    def test_undo_does_not_overwrite_a_file_that_took_the_old_name(self):
        cfg = self.html_config(r'strip = ["\\s*\\|\\s*SiteName$"]')
        self.touch("1.mp4")
        self.run_cli(str(self.folder), "--apply", config=cfg)
        self.touch("1.mp4")   # a new download took the number again
        u = self.run_cli("--undo", str(self.undo_logs()[0]))
        self.assertEqual(u.returncode, 0, u.stderr)
        self.assertIn("already exists", u.stdout)
        self.assertEqual((self.folder / "1.mp4").read_text(), "video bytes of 1.mp4")
        self.assertEqual(self.names(), ["1.mp4", "First & Best.mp4"])   # the renamed file stays, the new one is untouched

    # ---- collisions ----

    def test_same_title_twice_gets_a_number_and_nothing_is_overwritten(self):
        cfg = self.html_config(r'strip = ["\\s*\\|\\s*SiteName$"]')
        self.touch("3.mp4", "4.mp4")
        (self.folder / "Same Title (2).mp4").write_text("old")   # already on disk
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["Same Title (2).mp4", "Same Title (3).mp4", "Same Title.mp4"])
        self.assertEqual((self.folder / "Same Title (2).mp4").read_text(), "old")

    def test_existing_file_with_the_title_is_not_overwritten(self):
        cfg = self.html_config(r'strip = ["\\s*\\|\\s*SiteName$"]')
        (self.folder / "taken.MP4").write_text("keep me")
        (self.folder / "Taken.mp4").write_text("keep me too")
        self.touch("7.mp4")
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(p.read_text() for p in self.folder.iterdir()), ["keep me", "keep me too", "video bytes of 7.mp4"])
        self.assertTrue((self.folder / "Taken (2).mp4").exists())

    # ---- missing titles ----

    def test_files_without_a_title_are_listed_and_left_alone(self):
        cfg = self.html_config()
        self.touch("1.mp4", "5.mp4", "6.mp4", "99.mp4")   # 5: no title tag, 6: blank title, 99: HTTP 404
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["5.mp4", "6.mp4", "99.mp4", "First & Best | SiteName.mp4"])
        self.assertIn("no title for 3 file(s)", r.stdout)
        for name, why in (("5.mp4", "no title"), ("6.mp4", "no title"), ("99.mp4", "HTTP 404")):
            self.assertRegex(r.stdout, r"  %s: .*%s" % (name.replace(".", r"\."), why))

    # ---- rerun ----

    def test_rerun_leaves_renamed_files_alone_and_handles_new_ones(self):
        cfg = self.html_config(r'strip = ["\\s*\\|\\s*SiteName$"]')
        self.touch("1.mp4")
        self.run_cli(str(self.folder), "--apply", config=cfg)
        self.server.requests.clear()
        again = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.names(), ["First & Best.mp4"])
        self.assertEqual(self.server.requests, [])   # nothing to look up
        self.assertIn("1 already named", again.stdout)
        self.assertEqual(len(self.undo_logs()), 1)   # nothing renamed, no new log

        self.touch("2.mkv")   # a new download, any time later
        later = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(self.names(), ["First & Best.mp4", "Second - part-one.mkv"])
        self.assertEqual([p for p, _ in self.server.requests], ["/page/2"])
        self.assertEqual(len(self.undo_logs()), 2, later.stdout)

    # ---- title sources, id regex, headers ----

    def test_json_title_by_field_path(self):
        cfg = self.write_config(f'url_template = "{self.base}/api/{{id}}"\ndelay_seconds = 0\ntitle_from = "json"\ntitle_json_path = "data.title"\n')
        self.touch("1.mp4", "2.mp4", "3.mp4")   # 2: field missing, 3: body is not JSON
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(self.names(), ["2.mp4", "3.mp4", "Json One.mp4"])
        self.assertIn("no title for 2 file(s)", r.stdout)

    def test_json_path_can_index_a_list(self):
        cfg = self.write_config(f'url_template = "{self.base}/api/{{id}}"\ndelay_seconds = 0\ntitle_from = "json"\ntitle_json_path = "items.0.name"\n')
        self.touch("1.mp4")
        self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(self.names(), ["Json One.mp4"])

    def test_regex_title_with_one_group(self):
        cfg = self.write_config(f'url_template = "{self.base}/rx/{{id}}"\ndelay_seconds = 0\ntitle_from = "regex"\ntitle_regex = "<h1 class=\'t\'>(.*?)</h1>"\n')
        self.touch("1.mp4")
        self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(self.names(), ["Regex One.mp4"])

    def test_id_regex_picks_the_id_out_of_a_longer_name(self):
        cfg = self.html_config(r'id_regex = "^vid-([0-9]+)$"' + "\n" + r'strip = ["\\s*\\|\\s*SiteName$"]')
        self.touch("vid-1.mp4", "12.mp4")   # 12 is not in the pattern, so it is not touched
        self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(self.names(), ["12.mp4", "First & Best.mp4"])

    def test_headers_come_from_a_file(self):
        (self.home / "headers.txt").write_text("# comment\nCookie: session=abc\n")
        cfg = self.write_config(f'url_template = "{self.base}/cookie/{{id}}"\ndelay_seconds = 0\nheaders_file = "{self.home}/headers.txt"\n')
        self.touch("1.mp4")
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.names(), ["Cookie Title.mp4"])
        no_headers = self.write_config(f'url_template = "{self.base}/cookie/{{id}}"\ndelay_seconds = 0\n', "plain.toml")
        self.touch("1.mp4")
        r = self.run_cli(str(self.folder), config=no_headers)
        self.assertIn("1.mp4: HTTP 403", r.stdout)

    # ---- names and delay ----

    def test_long_titles_are_cut_to_the_macos_name_limit_and_keep_the_extension(self):
        PAGES["/page/8"] = (200, "text/html", "<title>%s</title>" % ("é" * 300))
        self.addCleanup(PAGES.pop, "/page/8")
        cfg = self.html_config()
        self.touch("8.mp4")
        self.run_cli(str(self.folder), "--apply", config=cfg)
        (name,) = self.names()
        self.assertTrue(name.endswith(".mp4"))
        self.assertLessEqual(len(name.encode()), 255)
        self.assertTrue(name.startswith("é"))

    def test_delay_between_requests_is_settable(self):
        cfg = self.html_config("")
        self.touch("1.mp4", "2.mkv", "3.mp4")
        start = time.monotonic()
        r = self.run_cli(str(self.folder), "--delay", "0.4", config=cfg)
        elapsed = time.monotonic() - start
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.server.requests), 3)
        self.assertGreaterEqual(elapsed, 0.8)   # 3 requests, 2 waits of 0.4s

    def test_same_long_title_twice_still_gets_a_number(self):
        cfg = self.html_config()
        self.touch("9.mp4")
        self.assertEqual(self.run_cli(str(self.folder), "--apply", config=cfg).returncode, 0)
        self.touch("9.mp4")   # a new download whose page has the same 300-character title: the name is taken
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        names = self.names()
        self.assertEqual(len(names), 2)
        self.assertTrue(any(n.endswith(" (2).mp4") for n in names), names)   # the suffix survives the cut to 255 bytes
        self.assertTrue(all(len(n.encode()) <= 255 for n in names), names)

    def test_a_title_that_is_only_digits_is_left_numeric_so_reruns_stay_safe(self):
        cfg = self.html_config(r'strip = ["\\s*\\|\\s*SiteName$"]')
        self.touch("14.mp4", "1.mp4")
        first = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.names(), ["14.mp4", "First & Best.mp4"])   # 14's title is "1984": not renamed
        self.assertRegex(first.stdout, r"14\.mp4: .*look like an id")
        second = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.names(), ["14.mp4", "First & Best.mp4"])
        self.assertNotIn("/page/1984", [p for p, _ in self.server.requests])   # nobody was looked up as id 1984
        self.assertEqual(len(self.undo_logs()), 1)

    def test_an_id_regex_that_matches_digits_inside_titles_leaves_those_files_alone(self):
        cfg = self.html_config('id_regex = "([0-9]+)"\n')   # unanchored: any name with digits looks numbered
        PAGES["/page/20"] = (200, "text/html", "<title>Top 10 Moments</title>")
        self.addCleanup(PAGES.pop, "/page/20")
        self.touch("20.mp4")
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(self.names(), ["20.mp4"])
        self.assertIn("look like an id", r.stdout)

    def test_html_codes_are_decoded_in_every_title_mode(self):
        rx = self.write_config(f'url_template = "{self.base}/rx/{{id}}"\ndelay_seconds = 0\ntitle_from = "regex"\ntitle_regex = "<h1 class=\'t\'>(.*?)</h1>"\n')
        self.touch("2.mp4")
        self.run_cli(str(self.folder), "--apply", config=rx)
        self.assertEqual(self.names(), ["Don't Stop & Go.mp4"])
        js = self.write_config(f'url_template = "{self.base}/api/{{id}}"\ndelay_seconds = 0\ntitle_from = "json"\ntitle_json_path = "data.title"\n', "j.toml")
        self.touch("4.mp4")
        self.run_cli(str(self.folder), "--apply", config=js)
        self.assertIn("Fish & Chips.mp4", self.names())

    def test_nfc_and_nfd_spellings_of_a_name_are_one_file(self):
        cfg = self.html_config()
        (self.folder / "Cafe\u0301.mp4").write_text("already here")   # NFD; the title below is NFC
        self.touch("13.mp4")
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(p.read_text() for p in self.folder.iterdir()), ["already here", "video bytes of 13.mp4"])
        self.assertEqual(len(self.names()), 2)
        self.assertTrue(any("(2)" in n for n in self.names()))

    def test_a_failure_partway_through_apply_names_the_undo_log(self):
        cfg = self.html_config()
        self.touch("10.mp4", "11.mp4", "12.mp4")
        # while 12's page is being fetched, "Late.mp4" appears: 11.mp4 -> Late.mp4 would then overwrite it
        self.server.hooks["/page/12"] = lambda: (self.folder / "Late.mp4").write_text("appeared late")
        r = self.run_cli(str(self.folder), "--apply", config=cfg)
        self.assertEqual(r.returncode, 1)
        log = self.undo_logs()[0]
        self.assertIn(str(log), r.stderr)
        self.assertIn("refusing to overwrite", r.stderr)
        self.assertEqual(self.names(), ["11.mp4", "12.mp4", "Early.mp4", "Late.mp4"])   # 10 was renamed; nothing was overwritten
        self.assertEqual((self.folder / "Late.mp4").read_text(), "appeared late")
        u = self.run_cli("--undo", str(log))
        self.assertEqual(u.returncode, 0, u.stderr)
        self.assertEqual(self.names(), ["10.mp4", "11.mp4", "12.mp4", "Late.mp4"])

    # ---- errors ----

    def test_missing_config_and_missing_folder_fail_with_one_line(self):
        r = self.run_cli(str(self.folder), "--config", str(self.home / "nope.toml"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no config at", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        r = self.run_cli(str(self.home / "nofolder"), config=self.html_config())
        self.assertEqual(r.returncode, 1)
        self.assertIn("is not a folder", r.stderr)


if __name__ == "__main__":
    unittest.main()
