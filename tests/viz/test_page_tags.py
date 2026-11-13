#!/usr/bin/env python3
"""Black-box tests for the page.json tag file that `viz publish` uploads beside each page.

The site is a small HTTP server in this process (like tests/viz/test_publish.py); the command is the real `viz` wrapper.
Most tests publish a saved render by id, which needs only node. The one test that publishes a file also renders it, so it
needs Chromium. MachineProfile renders the real chezmoi template for each profile, so it needs chezmoi.
Run: python3 tests/viz/test_page_tags.py [TagFile|MachineProfile|ThreadAndFlags|Refusal|Republish|ActionLog]
"""
import base64
import datetime
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VIZ = os.path.join(ROOT, "dot_local", "bin", "executable_viz")
NODE = shutil.which("node")
CHEZMOI = shutil.which("chezmoi")
CHROMIUM = bool(os.environ.get("VIZ_CHROMIUM") or shutil.which("chromium"))
PASSWORD = "test-password-not-a-secret"
RENDER_ID = "20261028-120000-000-abc123"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16 + b"rest of a png"
WITH_TITLE = b"<!doctype html><html><head><title>Quarterly  numbers &amp; trends</title></head><body><h1>Other</h1></body></html>\n"
WITH_H1 = b"<!doctype html><html><body><h1 class=big>The <em>big</em> picture</h1><h1>second</h1></body></html>\n"
BARE = b"<!doctype html><p>chart</p>\n"
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "T3CODE_THREAD_ID", "HERDR_ENV", "CODEX_SANDBOX")


class Site(http.server.BaseHTTPRequestHandler):
    files = {}

    def do_PUT(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        want = "Basic " + base64.b64encode(("viz:" + PASSWORD).encode()).decode()
        if self.headers.get("Authorization") != want:
            self.send_response(401)
            self.end_headers()
            return
        self.files[self.path] = (body, self.headers.get("Content-Type"))
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args):
        pass


class TagTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Site.files = {}
        self.state = tempfile.TemporaryDirectory(prefix="viz-tag-state-")
        self.addCleanup(self.state.cleanup)
        self.seed(RENDER_ID, BARE, "/in/chart.html")
        self.bin = tempfile.mkdtemp(prefix="viz-tag-bin-")
        self.addCleanup(shutil.rmtree, self.bin)
        os.symlink(NODE, os.path.join(self.bin, "node"))
        # No agent marker, no 1Password op on PATH, the password set: a plain terminal publish.
        self.env = {"PATH": self.bin + ":/usr/bin:/bin", "HOME": self.state.name, "VIZ_STATE_DIR": self.state.name,
                    "VIZ_PUBLISH_URL": self.base + "/", "VIZ_PUBLISH_PASSWORD": PASSWORD}

    def seed(self, render_id, page, input_path):
        folder = os.path.join(self.state.name, render_id)
        os.mkdir(folder)
        meta = {"id": render_id, "created": "2026-10-28T12:00:00.000Z", "as": "html", "input": input_path,
                "png": os.path.join(folder, "image.png"), "html": os.path.join(folder, "page.html"),
                "source": os.path.join(folder, "source.html"), "width": 0, "height": 0, "bytes": len(PNG)}
        for name, data in (("image.png", PNG), ("page.html", page), ("source.html", page), ("meta.json", json.dumps(meta).encode())):
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)

    def viz(self, *args, env=None, code=0):
        e = dict(self.env)
        for k, v in (env or {}).items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
        r = subprocess.run([VIZ, *args], capture_output=True, text=True, env=e, timeout=120)
        out = json.loads(r.stdout)
        self.assertEqual(r.returncode, code, (out, r.stderr[-500:]))
        return out

    def tag(self, render_id=RENDER_ID):
        body, kind = Site.files["/%s/page.json" % render_id]
        self.assertEqual(kind, "application/json")
        return json.loads(body)

    def records(self):
        with open(os.path.join(self.state.name, "actions.jsonl")) as f:
            return [json.loads(line) for line in f]


class TagFile(TagTest):
    def test_keys_and_values(self):
        out = self.viz("publish", RENDER_ID)
        tag = self.tag()
        self.assertEqual(list(tag), ["v", "id", "title", "machine", "thread", "workstream", "ask", "source", "published_at"])
        self.assertEqual((tag["v"], tag["id"], tag["source"]), (1, RENDER_ID, "/in/chart.html"))
        self.assertEqual((tag["thread"], tag["workstream"], tag["ask"]), (None, None, None))
        self.assertEqual(tag["machine"], "personal")
        stamp = datetime.datetime.fromisoformat(tag["published_at"].replace("Z", "+00:00"))
        self.assertLess(abs((datetime.datetime.now(datetime.timezone.utc) - stamp).total_seconds()), 120)
        # The page and picture still go up beside it.
        self.assertEqual(sorted(Site.files), ["/%s/image.png" % RENDER_ID, "/%s/index.html" % RENDER_ID, "/%s/page.json" % RENDER_ID])
        self.assertEqual(out["url"], "%s/%s/" % (self.base, RENDER_ID))

    def test_title_comes_from_title_then_h1_then_the_file_name(self):
        for n, (page, want) in enumerate(((WITH_TITLE, "Quarterly numbers & trends"), (WITH_H1, "The big picture"), (BARE, "chart.html"))):
            render_id = "20261028-120000-01%d-abc123" % n
            self.seed(render_id, page, "/in/chart.html")
            self.viz("publish", render_id)
            self.assertEqual(self.tag(render_id)["title"], want, page)

    def test_a_page_from_stdin_has_no_source_and_no_file_name_title(self):
        self.seed("20261028-120000-001-abc123", BARE, "-")
        self.seed("20261028-120000-002-abc123", WITH_TITLE, "-")
        self.viz("publish", "20261028-120000-001-abc123")
        self.viz("publish", "20261028-120000-002-abc123")
        bare, titled = self.tag("20261028-120000-001-abc123"), self.tag("20261028-120000-002-abc123")
        self.assertEqual((bare["source"], bare["title"]), (None, None))
        self.assertEqual((titled["source"], titled["title"]), (None, "Quarterly numbers & trends"))

    @unittest.skipUnless(CHROMIUM, "needs chromium (or VIZ_CHROMIUM) on PATH")
    def test_publishing_a_file_records_the_same_source_as_publishing_its_id(self):
        page = os.path.join(self.state.name, "page-under-test.html")
        with open(page, "wb") as f:
            f.write(WITH_H1)
        env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
        out = self.viz("publish", page, env=env)
        first = self.tag(out["id"])
        self.assertEqual((first["source"], first["title"]), (page, "The big picture"))
        Site.files = {}
        self.viz("publish", out["id"], env=env)
        self.assertEqual(self.tag(out["id"])["source"], page)


@unittest.skipUnless(CHEZMOI, "needs chezmoi on PATH")
class MachineProfile(TagTest):
    # The local data keys the work profile requires (docs/profiles.md); placeholder values.
    WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
                 "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}

    def render_machine_file(self, profile):
        """What chezmoi would write to ~/.config/viz/machine for this profile, from the real source tree."""
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            os.mkdir(home)
            cfg = os.path.join(tmp, "chezmoi.yaml")
            data = self.WORK_DATA if profile == "axon-work-computer" else {}
            with open(cfg, "w") as f:
                f.write("data:\n  profile: %s\n" % profile + "".join("  %s: %s\n" % kv for kv in data.items()))
            r = subprocess.run([CHEZMOI, "--source", ROOT, "--config", cfg, "--config-format", "yaml", "--destination", home,
                                "cat", os.path.join(home, ".config", "viz", "machine")],
                               capture_output=True, text=True, env=dict(os.environ, HOME=home), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def install(self, text):
        os.makedirs(os.path.join(self.state.name, ".config", "viz"), exist_ok=True)
        with open(os.path.join(self.state.name, ".config", "viz", "machine"), "w") as f:
            f.write(text)

    def test_work_profile_records_work_and_every_other_profile_personal(self):
        for profile, want in (("axon-work-computer", "work"), ("personal", "personal")):
            with self.subTest(profile=profile):
                Site.files = {}
                self.install(self.render_machine_file(profile))
                self.viz("publish", RENDER_ID)
                self.assertEqual(self.tag()["machine"], want)

    def test_the_caller_cannot_choose_the_machine(self):
        self.install(self.render_machine_file("personal"))
        self.viz("publish", RENDER_ID, env={"VIZ_MACHINE": "work"})
        self.assertEqual(self.tag()["machine"], "personal")
        self.install("work\n")
        self.viz("publish", RENDER_ID, env={"VIZ_MACHINE": "personal"})
        self.assertEqual(self.tag()["machine"], "work")

    def test_no_machine_file_means_personal(self):
        self.viz("publish", RENDER_ID)
        self.assertEqual(self.tag()["machine"], "personal")


class ThreadAndFlags(TagTest):
    def test_thread_is_the_environment_variable_else_null(self):
        self.viz("publish", RENDER_ID, env={"T3CODE_THREAD_ID": "thread-under-test"})
        self.assertEqual(self.tag()["thread"], "thread-under-test")
        self.viz("publish", RENDER_ID)
        self.assertIsNone(self.tag()["thread"])
        self.viz("publish", RENDER_ID, env={"T3CODE_THREAD_ID": ""})
        self.assertIsNone(self.tag()["thread"])

    def test_workstream_and_ask_are_recorded(self):
        self.viz("publish", RENDER_ID, "--workstream", "artifact-discovery", "--ask", "923")
        tag = self.tag()
        self.assertEqual((tag["workstream"], tag["ask"]), ("artifact-discovery", 923))
        self.viz("publish", RENDER_ID, "--workstream=other", "--ask=7")
        tag = self.tag()
        self.assertEqual((tag["workstream"], tag["ask"]), ("other", 7))

    def test_each_flag_alone_and_with_a_thread(self):
        self.viz("publish", RENDER_ID, "--ask", "5", env={"T3CODE_THREAD_ID": "t-1"})
        tag = self.tag()
        self.assertEqual((tag["thread"], tag["workstream"], tag["ask"]), ("t-1", None, 5))

    def test_bad_flag_values(self):
        for args in (("--ask", "abc"), ("--ask", "0"), ("--workstream", " "), ("--ask",)):
            self.assertEqual(self.viz("publish", RENDER_ID, *args, code=2)["code"], "bad_input", args)
        self.assertEqual(Site.files, {})

    def test_flags_are_not_passed_on_to_the_render(self):
        # A file that does not exist fails as a missing file, not as an unknown option.
        out = self.viz("publish", "/no/such/page.html", "--workstream", "w", "--ask", "3", code=2)
        self.assertEqual(out["code"], "bad_input")
        self.assertIn("no such file", out["message"])


class Refusal(TagTest):
    def test_each_agent_marker_without_thread_or_flag_is_refused_before_anything_happens(self):
        for marker in AGENT_MARKERS:
            if marker == "T3CODE_THREAD_ID":
                continue  # a thread id is itself the link; ThreadAndFlags and the next test cover it
            with self.subTest(marker=marker):
                # A file that does not exist: the refusal comes first, so it is not a missing-file error.
                out = self.viz("publish", "/no/such/page.html", env={marker: "1"}, code=6)
                self.assertEqual(out["code"], "unlinked_publish")
                self.assertIn("--workstream", out["message"])
                self.assertEqual(Site.files, {})

    def test_an_id_publish_is_refused_too_and_uploads_nothing(self):
        out = self.viz("publish", RENDER_ID, env={"CLAUDECODE": "1"}, code=6)
        self.assertEqual(out["code"], "unlinked_publish")
        self.assertEqual(Site.files, {})

    def test_a_thread_or_either_flag_lets_an_agent_shell_publish(self):
        for args, env in (((), {"T3CODE_THREAD_ID": "thread-under-test"}),
                          (("--workstream", "w"), {"CLAUDECODE": "1"}),
                          (("--ask", "9"), {"CLAUDECODE": "1", "HERDR_ENV": "1"}),
                          ((), {"CLAUDECODE": "1", "T3CODE_THREAD_ID": "t"})):
            with self.subTest(args=args, env=env):
                Site.files = {}
                self.assertTrue(self.viz("publish", RENDER_ID, *args, env=env)["ok"])
                self.assertIn("/%s/page.json" % RENDER_ID, Site.files)

    def test_a_terminal_with_no_marker_is_never_refused(self):
        out = self.viz("publish", RENDER_ID)
        self.assertTrue(out["ok"])
        self.assertEqual(self.tag()["thread"], None)

    def test_an_empty_marker_is_not_a_marker(self):
        self.assertTrue(self.viz("publish", RENDER_ID, env={"CLAUDECODE": "", "HERDR_ENV": ""})["ok"])


class Republish(TagTest):
    def test_a_second_publish_replaces_page_json_for_the_same_id_with_a_new_time(self):
        self.viz("publish", RENDER_ID, "--ask", "1")
        first = self.tag()
        paths = sorted(Site.files)
        Site.files = {}
        self.viz("publish", RENDER_ID, "--ask", "2")
        second = self.tag()
        self.assertEqual(sorted(Site.files), paths)
        self.assertEqual((second["id"], second["ask"]), (RENDER_ID, 2))
        self.assertNotEqual(second["published_at"], first["published_at"])
        self.assertGreater(second["published_at"], first["published_at"])  # ISO UTC strings sort by time


class ActionLog(TagTest):
    def test_a_publish_records_the_tag_it_wrote(self):
        self.viz("publish", RENDER_ID, "--workstream", "w", env={"T3CODE_THREAD_ID": "t-9"})
        record = self.records()[-1]
        steps = [s for s in record["steps"] if s["step"] == "tag"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["tag"], self.tag())
        self.assertEqual(steps[0]["tag"]["thread"], "t-9")
        uploads = [s["path"] for s in record["steps"] if s["step"] == "upload"]
        self.assertEqual(uploads[-1], "%s/page.json" % RENDER_ID)
        with open(os.path.join(self.state.name, "actions.jsonl")) as f:
            self.assertNotIn(PASSWORD, f.read())

    def test_a_refused_publish_records_the_refusal_code(self):
        out = self.viz("publish", RENDER_ID, env={"CLAUDECODE": "1"}, code=6)
        record = self.records()[-1]
        self.assertEqual((record["command"], record["args"]), ("publish", [RENDER_ID]))
        self.assertEqual(record["outcome"], out)
        self.assertEqual(record["outcome"]["code"], "unlinked_publish")
        self.assertEqual([s for s in record["steps"] if s["step"] in ("tag", "upload")], [])


if __name__ == "__main__":
    unittest.main()
