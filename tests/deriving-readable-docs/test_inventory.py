"""inventory.py: the literals a user or operator meets (messages, headers, routes, defaults, limits) as `kind | name | path:line`, on throwaway Python, TypeScript, Go and Rust repos.
Run: python3 -I tests/deriving-readable-docs/test_inventory.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"

FILES = {
    "src/app/server.py": '''import os, logging
logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 10_485_760
REQUEST_TIMEOUT = 30
LABEL = "not a limit at all"
HOME = os.environ.get("APP_HOME", "/var/lib/app")
# raise ValueError("a comment is not a message")


@app.get("/items")
def handler(request):
    token = request.headers["X-Api-Key"]
    auth = request.headers.get("Authorization")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")
    logger.info("Server is ready to accept requests")
    logger.debug("this debug line is not shown to anyone")
    print("Hello")
    return Response("Too many requests, slow down", status=429)


parser.add_argument("--port", default=8080)
''',
    "src/server.ts": '''const MAX_RESULTS = 50;
export const DEFAULT_TIMEOUT_MS = 30_000;
const retries = 3;
const title = "plain text with several words";
const port = process.env.PORT ?? 3000;
app.get("/admin", (req, res) => {
  const key = req.header("X-Admin-Token");
  if (!key) {
    res.status(403).send("Ask the site owner for access");
  }
  console.log("Listening on the configured port");
  throw new Error("The upstream service returned too many results");
});
''',
    "cmd/main.go": 'package main\n\nvar workers = flag.Int("workers", 4, "how many workers")\n\nfunc main() {\n\ttoken := r.Header.Get("X-Go-Token")\n\treturn errors.New("config file not found")\n}\n',
    "src/main.rs": 'const MAX_RETRIES: u32 = 5;\nfn run() { bail!("unsupported file format"); }\n',
    ".env.example": "# settings\nAPP_MODE=production\nCOOKIE_DOMAIN=example.org\n",
    "docker-compose.yml": "services:\n  web:\n    image: x\n    environment:\n      - LOG_LEVEL=${LOG_LEVEL:-info}\n",
    "tests/test_server.py": 'def test_x():\n    raise ValueError("A message that only a test holds")\nMAX_TEST_LIMIT = 9\n',
    "node_modules/dep/index.js": 'throw new Error("vendored failure message here");\n',
    "README.md": "# x\n",
}


def make_repo(files):
    tmp = tempfile.TemporaryDirectory()
    for rel, text in files.items():
        p = Path(tmp.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


def run(repo, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "inventory.py"), repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


class InventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = make_repo(FILES)
        code, out, err = run(cls.tmp.name, "--json")
        assert code == 0, err
        cls.rows = json.loads(out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def names(self, kind, file=None):
        return {r["name"] for r in self.rows if r["kind"] == kind and (file is None or r["file"] == file)}

    def test_python_messages_are_raised_logged_at_info_and_answered_and_a_debug_line_is_not_one(self):
        got = self.names("message", "src/app/server.py")
        self.assertEqual(got, {"Invalid or missing bearer token", "Server is ready to accept requests", "Too many requests, slow down"})

    def test_typescript_messages_are_thrown_logged_and_sent(self):
        self.assertEqual(self.names("message", "src/server.ts"), {"Ask the site owner for access", "Listening on the configured port", "The upstream service returned too many results"})

    def test_go_and_rust_messages(self):
        self.assertEqual(self.names("message", "cmd/main.go"), {"config file not found"})
        self.assertEqual(self.names("message", "src/main.rs"), {"unsupported file format"})

    def test_headers_that_are_read(self):
        self.assertEqual(self.names("header"), {"X-Api-Key", "Authorization", "Bearer", "X-Admin-Token", "X-Go-Token"})

    def test_routes_come_from_the_surface_scan(self):
        self.assertEqual(self.names("route"), {"/items", "/admin"})

    def test_defaults_carry_their_value(self):
        self.assertEqual(self.names("default"), {"APP_HOME = /var/lib/app", "port = 8080", "PORT = 3000", "workers = 4", "APP_MODE = production", "COOKIE_DOMAIN = example.org", "LOG_LEVEL = info"})

    def test_limits_are_named_numbers_that_cap_a_size_a_time_or_a_count(self):
        self.assertEqual(self.names("limit"), {"MAX_UPLOAD_BYTES = 10_485_760", "REQUEST_TIMEOUT = 30", "MAX_RESULTS = 50", "DEFAULT_TIMEOUT_MS = 30_000", "retries = 3", "MAX_RETRIES = 5"})

    def test_tests_comments_and_vendored_code_are_not_read(self):
        every = " ".join(r["name"] + r["file"] for r in self.rows)
        for word in ("only a test holds", "a comment is not a message", "vendored failure", "MAX_TEST_LIMIT", "tests/", "node_modules"):
            self.assertNotIn(word, every)

    def test_every_row_is_a_real_line_of_the_repo_that_holds_its_text(self):
        for r in self.rows:
            line = (Path(self.tmp.name) / r["file"]).read_text().split("\n")[r["line"] - 1]
            key = r["name"].split(" = ")[0] if r["kind"] in ("default", "limit") else r["name"]
            self.assertIn(key, line, r)

    def test_the_text_output_is_one_row_a_line_under_a_count_line(self):
        code, out, _ = run(self.tmp.name)
        self.assertEqual(code, 0)
        head, *rows = out.strip().split("\n")
        self.assertTrue(head.startswith("# "), head)
        self.assertIn("message | Invalid or missing bearer token | src/app/server.py:15", rows)
        self.assertEqual(len(rows), len(self.rows))

    def test_bad_usage_exits_2(self):
        self.assertEqual(subprocess.run([sys.executable, "-I", str(SCRIPTS / "inventory.py")], capture_output=True).returncode, 2)
        self.assertEqual(run("/no/such/folder")[0], 2)


if __name__ == "__main__":
    unittest.main()
