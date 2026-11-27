"""surfaces.py on a small repo per language, run as the skill runs it (as a script). A row must be a real line of the repo.
Run: python3 -I tests/deriving-readable-docs/test_surfaces.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"

FILES = {
    "pyproject.toml": '[project]\nname = "x"\n\n[project.scripts]\nxcli = "x.cli:main"\n',
    "src/x/cli.py": 'import argparse, os\np = argparse.ArgumentParser()\np.add_argument("--verbose")\nhome = os.environ.get("X_HOME")\nif __name__ == "__main__":\n    main()\n',
    "src/x/api.py": '@app.get("/items")\ndef items():\n    pass\n\n@click.option("--limit")\ndef run():\n    pass\n',
    "tests/test_cli.py": 'p.add_argument("--hidden-in-test")\n',
    "main.go": 'package main\n\nvar addr = flag.String("addr", ":80", "listen")\n\nfunc main() {\n\tmux.HandleFunc("/health", h)\n\tmux.HandleFunc("https://elsewhere.example/a", h)\n\ttok := os.Getenv("X_TOKEN")\n\tre := regexp.MustCompile(`^/v1/([a-z]+)$`)\n}\n',
    "cmd/serve.go": 'var cmd = &cobra.Command{\n\tUse: "serve",\n}\n\nvar flags = []cli.Flag{\n\t&cli.StringFlag{Name: "listen-http"},\n\t&cli.StringFlag{\n\t\tName: "base-url",\n\t},\n\t&cli.App{\n\t\tName: "not-a-flag",\n\t},\n}\n',
    "package.json": '{\n  "name": "x",\n  "bin": "./cli.js",\n  "scripts": {\n    "build": "tsc",\n    "test": "vitest"\n  }\n}\n',
    "web/cli.js": 'program.command("build");\nprogram.option("--out <dir>");\napp.get("/ping", (req, res) => {});\nsocket.on("hello", (s) => {});\nstream.on("close", () => {});\nconst k = process.env.API_KEY;\n',
    "Cargo.toml": '[package]\nversion = "1"\n\n[[bin]]\nname = "tool"\npath = "src/main.rs"\n',
    "src/main.rs": 'fn main() {}\n#[derive(Parser)]\nstruct Args {\n    #[arg(long)]\n    pub dry_run: bool,\n    #[arg(short, long = "out-dir")]\n    out: String,\n    #[arg(short)]\n    quiet: bool,\n}\nfn h() { let _ = env::var("TOOL_HOME"); }\n',
    "src/lib.rs": "pub fn run() {}\nfn private() {}\n",
    "src/web.rs": '#[get("/items")]\nasync fn items() {}\n\n#[post("/items/{id}")]\nasync fn add() {}\n\n#[get("not-a-path")]\nfn x() {}\n',
    "bin/deploy": '#!/bin/sh\ncase "$1" in\n  -v|--verbose) V=1;;\n  --region) shift;;\nesac\necho "${DEPLOY_ENV:-prod}" $OPTARG\nexport REGION=eu\n',
    "Dockerfile": 'FROM alpine\nENTRYPOINT ["x"]\n',
    "Makefile": ".PHONY: all\nall:\n\ttrue\nbuild: all\n\ttrue\nVAR := 1\n",
    ".github/workflows/ci.yml": "on: push\njobs:\n  t:\n    steps:\n      - run: make test\n",
    ".github/dependabot.yml": "version: 2\n",
    ".pre-commit-config.yaml": "repos: []\n",
    "conf/app.yml": "port: 80\n",
    "a/b/c/deep.yml": "x: 1\n",
    "docs/guide.md": "# Guide\n",
    "README.md": "# x\n",
    "node_modules/dep/index.js": 'app.get("/vendored", h);\n',
}


def make_repo(files):
    tmp = tempfile.TemporaryDirectory()
    for rel, text in files.items():
        p = Path(tmp.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


def run(repo, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "surfaces.py"), repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout


def line_of(path, needle):
    for i, l in enumerate(FILES[path].split("\n"), 1):
        if needle in l:
            return i
    raise AssertionError("%r is not in %s" % (needle, path))


class SurfacesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = make_repo(FILES)
        code, out = run(cls.tmp.name, "--json")
        assert code == 0, out
        cls.rows = json.loads(out)
        cls.have = {(r["kind"], r["name"], r["file"], r["line"]) for r in cls.rows}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def has(self, kind, name, path, needle):
        row = (kind, name, path, line_of(path, needle))
        self.assertIn(row, self.have, "missing %s in %s" % (row, sorted(r for r in self.have if r[2] == path)))

    def test_every_row_is_a_line_of_the_repo(self):
        for r in self.rows:
            lines = FILES[r["file"]].split("\n")
            self.assertTrue(1 <= r["line"] <= len(lines), r)
            if r["kind"] not in ("manifest", "doc", "config", "ci"):
                self.assertTrue(lines[r["line"] - 1].strip() or r["line"] == 1, r)

    def test_python(self):
        self.has("entry", "script xcli", "pyproject.toml", "xcli =")
        self.has("flag", "--verbose", "src/x/cli.py", "add_argument")
        self.has("env", "X_HOME", "src/x/cli.py", "X_HOME")
        self.has("entry", 'if __name__ == "__main__":', "src/x/cli.py", "__main__")
        self.has("route", "/items", "src/x/api.py", "@app.get")
        self.has("flag", "--limit", "src/x/api.py", "@click.option")

    def test_go(self):
        self.has("entry", "package main", "main.go", "package main")
        self.has("flag", "addr", "main.go", "flag.String")
        self.has("route", "/health", "main.go", "/health")
        self.has("route", "^/v1/([a-z]+)$", "main.go", "regexp.MustCompile")
        self.has("env", "X_TOKEN", "main.go", "X_TOKEN")
        self.has("command", "serve", "cmd/serve.go", "Use:")
        self.has("flag", "listen-http", "cmd/serve.go", "listen-http")

    def test_a_go_url_is_not_a_route(self):
        self.assertFalse([r for r in self.rows if "elsewhere" in r["name"]])

    def test_urfave_flag_with_fields_on_their_own_lines_is_a_flag_but_an_app_name_is_not(self):
        self.has("flag", "base-url", "cmd/serve.go", "base-url")
        self.assertFalse([r for r in self.rows if r["name"] == "not-a-flag"])

    def test_js_and_ts(self):
        self.has("entry", 'bin "./cli.js"', "package.json", '"bin"')
        self.has("entry", "script build", "package.json", '"build"')
        self.has("entry", "script test", "package.json", '"test"')
        self.has("command", "build", "web/cli.js", ".command(")
        self.has("flag", "--out <dir>", "web/cli.js", ".option(")
        self.has("route", "/ping", "web/cli.js", "app.get")
        self.has("event", "hello", "web/cli.js", "socket.on")
        self.has("env", "API_KEY", "web/cli.js", "API_KEY")

    def test_a_generic_close_event_is_noise(self):
        self.assertFalse([r for r in self.rows if r["kind"] == "event" and r["name"] == "close"])

    def test_rust_flags_are_named_by_their_field_or_long_name_not_by_the_attribute(self):
        self.has("entry", "bin tool", "Cargo.toml", "name = \"tool\"")
        self.has("entry", "src/main.rs", "src/main.rs", "fn main")
        self.has("flag", "--dry-run", "src/main.rs", "#[arg(long)]")
        self.has("flag", "--out-dir", "src/main.rs", "out-dir")
        self.has("flag", "-q", "src/main.rs", "#[arg(short)]")
        self.has("env", "TOOL_HOME", "src/main.rs", "TOOL_HOME")
        self.has("route", "/items", "src/web.rs", '#[get("/items")]')
        self.has("route", "/items/{id}", "src/web.rs", '#[post("/items/{id}")]')
        self.assertFalse([r for r in self.rows if r["kind"] == "route" and r["file"] == "src/web.rs" and "not-a-path" in r["name"]])  # a path with no leading / is not a route
        self.has("export", "run", "src/lib.rs", "pub fn run")
        self.assertFalse([r for r in self.rows if r["name"] == "private"])

    def test_shell_scripts_with_a_shebang_and_no_extension(self):
        self.has("entry", "script deploy", "bin/deploy", "#!/bin/sh")
        self.has("flag", "-v/--verbose", "bin/deploy", "-v|--verbose")
        self.has("flag", "--region", "bin/deploy", "--region")
        self.has("env", "DEPLOY_ENV", "bin/deploy", "DEPLOY_ENV")
        self.has("env", "REGION", "bin/deploy", "export REGION")

    def test_shell_noise_is_dropped(self):
        self.assertFalse([r for r in self.rows if r["name"] == "OPTARG"])

    def test_dockerfile_makefile_ci_docs_and_config(self):
        self.has("entry", 'ENTRYPOINT ["x"]', "Dockerfile", "ENTRYPOINT")
        self.has("command", "make all", "Makefile", "all:")
        self.has("command", "make build", "Makefile", "build:")
        self.assertFalse([r for r in self.rows if r["name"] in ("make .PHONY", "make VAR")])
        self.has("ci", "make test", ".github/workflows/ci.yml", "run:")
        self.has("config", "app.yml", "conf/app.yml", "port")
        self.has("doc", "README.md", "README.md", "# x")
        self.has("doc", "guide.md", "docs/guide.md", "# Guide")

    def test_tooling_files_deep_files_vendored_code_and_tests_are_not_surfaces(self):
        files = {r["file"] for r in self.rows}
        self.assertNotIn(".github/dependabot.yml", files)
        self.assertNotIn(".pre-commit-config.yaml", files)
        self.assertNotIn("a/b/c/deep.yml", files)
        self.assertNotIn("node_modules/dep/index.js", files)
        self.assertNotIn("tests/test_cli.py", files)

    def test_text_output_is_kind_name_and_path_line_grouped_by_kind(self):
        code, out = run(self.tmp.name)
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("# "), lines[0])
        self.assertIn("flag | --verbose | src/x/cli.py:3", lines)
        kinds = [l.split(" | ")[0] for l in lines[1:]]
        self.assertEqual(kinds, sorted(kinds, key=["entry", "command", "flag", "route", "event", "env", "config", "manifest", "export", "doc", "ci"].index))

    def test_a_git_checkout_lists_only_tracked_files(self):
        with make_repo({"a.py": 'p.add_argument("--tracked")\n', "ignored.py": 'p.add_argument("--untracked")\n'}) as d:
            subprocess.run(["git", "-C", d, "init", "-q"], check=True)
            subprocess.run(["git", "-C", d, "add", "a.py"], check=True)
            code, out = run(d)
        self.assertIn("--tracked", out)
        self.assertNotIn("--untracked", out)

    def test_bad_usage_exits_2(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "surfaces.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(run("/no/such/folder")[0], 2)


class ResolveTest(unittest.TestCase):
    def resolve(self, names):
        with make_repo(FILES) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "names.txt").write_text(names)
            return run(repo, "--resolve", str(Path(d, "names.txt")))

    def test_a_name_in_the_code_resolves_to_a_line_and_one_that_is_not_there_is_not_found(self):
        code, out = self.resolve("# scout\n/health\nserve\nteleport\n")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["/health | main.go:%d" % line_of("main.go", "/health"), "serve | cmd/serve.go:%d" % line_of("cmd/serve.go", "Use:"),
                                            "teleport | NOT FOUND"])

    def test_a_name_that_only_a_test_holds_is_a_weak_match_and_one_only_a_doc_or_vendored_code_holds_is_not_found(self):
        code, out = self.resolve("--hidden-in-test\nGuide\n/vendored\n")
        self.assertEqual(out.splitlines(), ["--hidden-in-test | WEAK MATCH tests/test_cli.py:1", "Guide | NOT FOUND", "/vendored | NOT FOUND"])

    def test_a_quoted_line_wins_over_an_earlier_bare_one(self):
        files = {"a.py": "# build the thing\n", "b.py": 'cmd = "build"\n'}
        with make_repo(files) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "n.txt").write_text("build\n")
            code, out = run(repo, "--resolve", str(Path(d, "n.txt")))
        self.assertEqual(out.strip(), "build | b.py:1")

    def test_a_missing_names_file_is_a_usage_error(self):
        with make_repo(FILES) as repo:
            self.assertEqual(run(repo, "--resolve", "/no/such")[0], 2)


# A TS repo built like agent-kit: no package.json bin, each command line reached through a run function with a default program name, a
# `case` dispatch, `command === 'x'` tests and parseArgs option tables.
TS_CLI = {
    "package.json": '{\n  "name": "kit",\n  "exports": {}\n}\n',
    "src/reach/cli.ts": "import { parseArgs } from 'node:util';\nconst OPTIONS = {\n  text: { type: 'string' },\n  'reply-to': { type: 'string' },\n  'as-file': { type: 'boolean' },\n} as const;\n"
                        "export function run(argv: string[], { program = 'reach' }: CliEnv): number {\n  const [command, ...rest] = argv;\n"
                        "  if (command !== 'send' && command !== 'react') return 2;\n  return 0;\n}\n",
    "src/jobs/cli.ts": "import { parseArgs } from 'node:util';\nexport async function runJobsCli(argv: string[], { program = 'jobs' }: Options) {\n  switch (verb) {\n    case 'list':\n      return 0;\n"
                       "    case 'add': {\n      return 1;\n    }\n    case 'remove':\n      return 2;\n  }\n}\n",
    "src/board/cli.ts": "import { parseArgs } from 'node:util';\nconst bad = () => err(`usage: board <${names}> [args]`);\n"
                        "const o = parseArgs({ args, options: { dir: { type: 'string' }, 'tick-id': str, all: { type: 'boolean' } }, strict: true });\n",
    "src/traces/cli.ts": "import { parseArgs } from 'node:util';\nconst USAGE = [\n  'usage: traces review normalize <findings.json>',\n  'usage: traces review add <file>',\n];\n",
    "src/playbook/cli.ts": "export function run(options) {\n  const { program = 'playbook' } = options;\n  if (command === 'show') return 0;\n  if (command === 'add') return 1;\n  return process.argv.length;\n}\n",
    "src/other/state.ts": "switch (kind) {\n  case 'open':\n    return 1;\n}\nconst x = command === 'not-a-cli';\n",
}


def ts_rows(files):
    with make_repo(files) as repo:
        code, out = run(repo, "--json")
        assert code == 0, out
        return json.loads(out)


class TsCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = ts_rows(TS_CLI)
        cls.cmds = {(r["name"], r["file"]) for r in cls.rows if r["kind"] == "command"}
        cls.flags = {(r["name"], r["file"]) for r in cls.rows if r["kind"] == "flag"}

    def line(self, path, needle):
        for i, l in enumerate(TS_CLI[path].split("\n"), 1):
            if needle in l:
                return i

    def test_the_five_command_lines_are_found_by_their_default_program_name_or_usage_line(self):
        for name, path in (("reach", "src/reach/cli.ts"), ("jobs", "src/jobs/cli.ts"), ("playbook", "src/playbook/cli.ts"), ("board", "src/board/cli.ts"), ("traces", "src/traces/cli.ts")):
            self.assertIn((name, path), self.cmds, sorted(self.cmds))

    def test_a_usage_line_that_repeats_is_one_row_and_names_the_first_line(self):
        rows = [r for r in self.rows if r["kind"] == "command" and r["name"] == "traces"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line"], self.line("src/traces/cli.ts", "usage: traces review normalize"))

    def test_case_arms_and_command_tests_in_a_file_that_reads_argv_are_subcommands(self):
        for name in ("list", "add", "remove"):
            self.assertIn((name, "src/jobs/cli.ts"), self.cmds)
        self.assertIn(("send", "src/reach/cli.ts"), self.cmds)
        self.assertIn(("react", "src/reach/cli.ts"), self.cmds)
        self.assertIn(("show", "src/playbook/cli.ts"), self.cmds)

    def test_a_switch_or_comparison_in_a_file_that_reads_no_argv_is_not_a_command(self):
        self.assertFalse([r for r in self.rows if r["file"] == "src/other/state.ts" and r["kind"] == "command"])

    def test_parse_args_option_names_are_flags(self):
        for name in ("--text", "--reply-to", "--as-file"):
            self.assertIn((name, "src/reach/cli.ts"), self.flags)
        for name in ("--dir", "--tick-id", "--all"):
            self.assertIn((name, "src/board/cli.ts"), self.flags)
        self.assertNotIn(("--type", "src/board/cli.ts"), self.flags)

    def test_every_row_is_a_literal_line_of_the_repo(self):
        for r in self.rows:
            if r["kind"] in ("command", "flag"):
                self.assertTrue(r["file"] in TS_CLI and 1 <= r["line"] <= len(TS_CLI[r["file"]].split("\n")), r)
                self.assertTrue(TS_CLI[r["file"]].split("\n")[r["line"] - 1].strip(), r)

    def test_a_package_json_bin_is_still_an_entry(self):
        rows = ts_rows(dict(TS_CLI, **{"package.json": '{\n  "bin": { "kit": "./cli.js" }\n}\n'}))
        self.assertTrue([r for r in rows if r["kind"] == "entry" and r["name"].startswith("bin")])


class ResolveDefinitionTest(unittest.TestCase):
    def resolve(self, files, name):
        with make_repo(files) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "n.txt").write_text(name + "\n")
            return run(repo, "--resolve", str(Path(d, "n.txt")))[1].strip()

    def test_the_definition_wins_over_an_earlier_use(self):
        files = {"a.ts": "import { runBoard } from './b.ts';\nrunBoard();\n", "b.ts": "export function runBoard() {\n}\n"}
        self.assertEqual(self.resolve(files, "runBoard"), "runBoard | b.ts:1")

    def test_python_def_class_and_const_are_definitions(self):
        self.assertEqual(self.resolve({"a.py": "x = Thing()\n", "b.py": "class Thing:\n    pass\n"}, "Thing"), "Thing | b.py:1")
        self.assertEqual(self.resolve({"a.py": "run_it()\n", "b.py": "def run_it():\n    pass\n"}, "run_it"), "run_it | b.py:1")
        self.assertEqual(self.resolve({"a.ts": "use(LIMIT);\n", "b.ts": "export const LIMIT = 5;\n"}, "LIMIT"), "LIMIT | b.ts:1")

    def test_a_go_method_definition_wins_too(self):
        self.assertEqual(self.resolve({"a.go": "s.Serve()\n", "b.go": "func (s *S) Serve() {\n}\n"}, "Serve"), "Serve | b.go:1")

    def test_with_no_definition_the_quoted_line_still_wins_over_the_bare_one(self):
        self.assertEqual(self.resolve({"a.py": "# build it\n", "b.py": 'cmd = "build"\n'}, "build"), "build | b.py:1")


class SnapshotFolderTest(unittest.TestCase):
    def test_a_snapshot_folder_is_never_a_source_of_surfaces(self):
        tmp = make_repo({"web/cli.js": 'app.get("/ping", h);\n', "docs/snapshots/2026-01-01-aaaaaaa/cli.js": 'app.get("/only-in-a-snapshot", h);\n'})
        with tmp:
            code, out = run(tmp.name, "--json")
        self.assertEqual(code, 0)
        self.assertIn("/ping", out)
        self.assertNotIn("only-in-a-snapshot", out)


if __name__ == "__main__":
    unittest.main()
