"""surfaces.py on the forms a recall check found it could not see. Every snippet is copied from a real repo (named at its entry):
vaultwarden, ntfy, lapce, uptime-kuma. A row must still be a real line of the repo.
Run: python3 -I tests/deriving-readable-docs/test_surfaces_recall.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"

FILES = {
    # vaultwarden src/api/web.rs, src/api/notifications.rs; plus a call-style `get(` that is not an attribute
    "src/api/web.rs": '// We use DbConn here to let the alive healthcheck also verify the database connection.\n#[get("/alive")]\nfn alive(_conn: DbConn) -> Json<String> {\n    now()\n}\n\n'
                      '#[post("/hub?<data..>", data = "<body>")]\nfn hub() {}\n#[delete("/x")]\nfn x() {}\n#[put("/y")]\nfn y() {}\n#[head("/z")]\nfn z() {}\n'
                      '#[route(GET, path = "/ping")]\nfn p() {}\nlet r = get("/not-an-attribute");\n',
    # ntfy server/server.go: the paths are constants, and the handler tests `r.URL.Path == apiHealthPath`
    "server/server.go": 'var (\n\taccountPath                                          = "/account"\n\tmatrixPushPath                                       = "/_matrix/push/v1/notify"\n'
                        '\tapiHealthPath                                        = "/v1/health"\n\tapiReadyPath                                         = "/v1/ready"\n\tcachePath                                            = "/var/cache/ntfy"\n\twebSiteDir                                           = "/site"\n)\n\n'
                        'func (s *Server) handleInternal(w http.ResponseWriter, r *http.Request, v *visitor) error {\n\tif r.Method == http.MethodHead && r.URL.Path == "/" {\n\t\treturn s.handleEmpty(w, r, v)\n'
                        '\t} else if r.Method == http.MethodGet && r.URL.Path == apiHealthPath {\n\t\treturn s.handleHealth(w, r, v)\n\t} else if r.Method == http.MethodGet && r.URL.Path == apiReadyPath {\n\t\treturn s.handleReady(w, r, v)\n\t}\n'
                        '\tos.MkdirAll(cachePath, 0700)\n\tr.URL.Path = webSiteDir + r.URL.Path\n}\n',
    # ntfy client/config.go
    "client/config.go": 'package client\n\nconst (\n\t// DefaultBaseURL is the base URL used to expand short topic names\n\tDefaultBaseURL = "https://ntfy.sh"\n)\n\n'
                        '// DefaultConfigFile is the default path to the client config file (set in config_*.go)\nvar DefaultConfigFile string\n\nconst notDefault = 1\n',
    # vaultwarden src/config.rs: the make_config! table; `_ip_header_enabled` is a generated field
    "src/config.rs": 'make_config! {\n    folders {\n        ///  Data folder |> Main data folder\n        data_folder:            String, false,  def,    "data".to_owned();\n'
                     '        /// Password iterations |> Number of server-side passwords hashing iterations for the password hash.\n        password_iterations:    i32,    true,   def,    600_000;\n'
                     '        /// Log level |> Valid values are "trace", "debug", "info", "warn", "error" and "off"\n        log_level:              String, false,  def,    "info".to_owned();\n    },\n'
                     '    /// Advanced settings\n    advanced {\n        /// Client IP header |> If not present, the remote IP is used.\n        ip_header:              String, true,   def,    "X-Real-IP".to_owned();\n'
                     '        /// Internal IP header property, used to avoid recomputing each time\n        _ip_header_enabled:     bool,   false,  generated,    |c| !c.ip_header.trim().eq_ignore_ascii_case("none");\n'
                     '        /// Icon blacklist\n        icon_blacklist_regex:   String, false,  option;\n    },\n}\n\nfn other() {\n    let note: String, i32;\n}\n',
    # vaultwarden src/util.rs
    "src/util.rs": 'pub fn get_env_str_value(key: &str) -> Option<String> {\n    let key_file = format!("{key}_FILE");\n    let value_from_env = env::var(key);\n    let value_file = env::var(&key_file);\n}\n',
    # lapce defaults/settings.toml (`wrap-column` has no struct field here, so it is not a setting row). The theme and keymap files share key names only by chance.
    "defaults/settings.toml": '#:schema ../extra/schemas/settings.json\n\n[core]\nmodal = false\ncolor-theme = "Lapce Dark"\n\n[editor]\nfont-family = "monospace"\nfont-size = 13\nwrap-column = 80\n'
                              'format-on-save = false\nautosave-interval = 0\nformat-on-autosave = true\n',
    "defaults/dark-theme.toml": '[ui]\nfont-family = "Inter"\nfont-size = 13\n\n[color-theme]\nbase = "dark"\nbackground = "#000"\nforeground = "#fff"\n',
    "defaults/keymaps-common.toml": '[[keymaps]]\nkey = "ctrl+s"\ncommand = "save"\nautosave-interval = 5\n',
    # lapce lapce-app/src/config/editor.rs and terminal.rs
    "lapce-app/src/config/editor.rs": '    #[field_names(desc = "Modal editing.")]\n    pub modal: bool,\n    #[field_names(desc = "The theme.")]\n    pub color_theme: String,\n    #[field_names(desc = "Font.")]\n    pub font_family: String,\n'
                                      '    #[field_names(desc = "Size.")]\n    pub font_size: u32,\n    #[field_names(desc = "Format on save.")]\n    pub format_on_save: bool,\n    #[field_names(desc = "Whether the editor show indent guide.")]\n    pub show_indent_guide: bool,\n    #[field_names(\n        desc = "Set the auto save delay (in milliseconds), Set to 0 to completely disable"\n    )]\n'
                                      '    pub autosave_interval: u64,\n    #[field_names(\n        desc = "Whether the document should be formatted when an autosave is triggered (required Format on Save)"\n    )]\n    pub format_on_autosave: bool,\n'
                                      '    #[field_names(skip)]\n    pub profiles: HashMap<String, TerminalProfile>,\n    pub undocumented: bool,\n',
    # lapce Cargo.toml
    "Cargo.toml": '[workspace]\nmembers = ["a"]\n\n[profile.release-lto]\ninherits      = "release"\nlto           = true\ncodegen-units = 1\n\n'
                  '# To use this profile:\n#   cargo build --profile fastdev\n[profile.fastdev.package."*"]\nopt-level = 3\n\n[profile.fastdev]\ninherits = "dev"\n',
    # uptime-kuma src/pages/EditMonitor.vue, and a second object that is not a defaults object
    "src/pages/EditMonitor.vue": 'const monitorDefaults = {\n    type: "http",\n    name: "",\n    parent: null,\n    url: defaultValueList.http.url,\n    interval: 60,\n'
                                 '    humanReadableInterval: timeDurationFormatter.secondsToHumanReadableFormat(60),\n    retryInterval: 60,\n    resendInterval: 0,\n    maxretries: 0,\n'
                                 '    retryOnlyOnStatusCodeFailure: false,\n    notificationIDList: {},\n    timeout: 48,\n};\n\nconst layout = {\n    width: 300,\n};\n\nconst defaults = {\n    pageLength: 10,\n};\n',
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


class RecallFormsTest(unittest.TestCase):
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

    def names(self, kind, path=None):
        return {r["name"] for r in self.rows if r["kind"] == kind and (path is None or r["file"] == path)}

    def test_every_row_is_a_literal_line_of_the_repo(self):
        for r in self.rows:
            lines = FILES[r["file"]].split("\n")
            self.assertTrue(1 <= r["line"] <= len(lines), r)
            if r["kind"] not in ("manifest", "doc", "config", "ci") or r["file"].endswith((".rs", ".go", ".vue")):
                self.assertTrue(lines[r["line"] - 1].strip(), r)

    # 1. Rust attribute routes
    def test_rust_attribute_routes_are_routes(self):
        self.has("route", "/alive", "src/api/web.rs", '#[get("/alive")]')
        self.has("route", "/hub?<data..>", "src/api/web.rs", "#[post(")
        self.has("route", "/x", "src/api/web.rs", "#[delete(")
        self.has("route", "/y", "src/api/web.rs", "#[put(")
        self.has("route", "/z", "src/api/web.rs", "#[head(")
        self.has("route", "/ping", "src/api/web.rs", "#[route(")

    def test_a_rust_call_that_is_not_an_attribute_is_not_a_route(self):
        self.assertNotIn("/not-an-attribute", self.names("route"))

    # 2. Go route constants and default constants
    def test_a_go_path_constant_that_the_handler_compares_to_the_request_path_is_a_route(self):
        self.has("route", "/v1/health", "server/server.go", 'apiHealthPath  ')
        self.has("route", "/v1/ready", "server/server.go", 'apiReadyPath  ')

    def test_a_go_path_constant_that_no_router_or_request_path_uses_is_not_a_route(self):
        names = self.names("route", "server/server.go")
        self.assertNotIn("/account", names)
        self.assertNotIn("/_matrix/push/v1/notify", names)
        self.assertNotIn("/var/cache/ntfy", names)
        self.assertNotIn("/site", names)  # `r.URL.Path = webSiteDir + r.URL.Path` rewrites the path; it is not a route

    def test_go_default_constants_are_config(self):
        self.has("config", "DefaultBaseURL", "client/config.go", "DefaultBaseURL =")
        self.assertNotIn("DefaultConfigFile", self.names("config"))  # no value on that line
        self.assertNotIn("notDefault", self.names("config"))

    # 3. make_config! settings
    def test_make_config_rows_are_upper_case_env_names_cited_in_the_declaring_file(self):
        self.has("env", "PASSWORD_ITERATIONS", "src/config.rs", "password_iterations:")
        self.has("env", "LOG_LEVEL", "src/config.rs", "log_level:")
        self.has("env", "IP_HEADER", "src/config.rs", "ip_header:")
        self.has("env", "DATA_FOLDER", "src/config.rs", "data_folder:")
        self.has("env", "ICON_BLACKLIST_REGEX", "src/config.rs", "icon_blacklist_regex:")

    def test_a_generated_or_underscore_field_is_not_a_setting(self):
        self.assertFalse({"_IP_HEADER_ENABLED", "IP_HEADER_ENABLED"} & self.names("env"))
        self.assertNotIn("NOTE", self.names("env"))

    def test_the_file_suffix_convention_is_one_env_row(self):
        self.has("env", "<NAME>_FILE", "src/util.rs", 'format!("{key}_FILE")')

    # 4. struct-field settings and their defaults file
    def test_field_names_fields_with_a_desc_are_settings_named_as_the_kebab_case_key(self):
        self.has("config", "autosave-interval", "lapce-app/src/config/editor.rs", "pub autosave_interval")
        self.has("config", "format-on-autosave", "lapce-app/src/config/editor.rs", "pub format_on_autosave")
        self.has("config", "show-indent-guide", "lapce-app/src/config/editor.rs", "pub show_indent_guide")
        self.assertNotIn("profiles", self.names("config"))  # field_names(skip)
        self.assertNotIn("undocumented", self.names("config"))

    def test_a_defaults_toml_key_that_is_a_declared_setting_carries_its_value_line(self):
        self.has("config", "editor.autosave-interval", "defaults/settings.toml", "autosave-interval = 0")
        self.has("config", "editor.format-on-autosave", "defaults/settings.toml", "format-on-autosave")

    def test_a_defaults_toml_key_that_is_not_a_declared_setting_is_left_out(self):
        self.assertNotIn("editor.wrap-column", self.names("config"))
        self.has("config", "core.modal", "defaults/settings.toml", "modal = false")

    def test_a_theme_or_keymap_file_that_shares_a_key_name_is_not_a_defaults_file(self):
        for f, base in (("defaults/dark-theme.toml", "dark-theme.toml"), ("defaults/keymaps-common.toml", "keymaps-common.toml")):
            self.assertEqual({r["name"] for r in self.rows if r["file"] == f}, {base})

    # 5. Cargo profiles
    def test_cargo_profiles_are_config_rows_but_their_package_subtables_are_not(self):
        self.has("config", "profile.release-lto", "Cargo.toml", "[profile.release-lto]")
        self.has("config", "profile.fastdev", "Cargo.toml", "[profile.fastdev]")
        self.assertFalse([n for n in self.names("config", "Cargo.toml") if "package" in n])

    # 6. frontend defaults object
    def test_the_numbers_in_a_frontend_defaults_object_are_config_rows(self):
        for key in ("interval", "retryInterval", "resendInterval", "maxretries", "timeout"):
            self.has("config", "monitorDefaults." + key, "src/pages/EditMonitor.vue", "    %s:" % key)

    def test_strings_nulls_references_calls_and_other_objects_in_it_are_left_out(self):
        names = self.names("config", "src/pages/EditMonitor.vue")
        for gone in ("monitorDefaults.type", "monitorDefaults.name", "monitorDefaults.parent", "monitorDefaults.url", "monitorDefaults.humanReadableInterval",
                     "monitorDefaults.notificationIDList", "monitorDefaults.retryOnlyOnStatusCodeFailure", "layout.width", "defaults.pageLength"):
            self.assertNotIn(gone, names)

    def test_resolve_finds_the_named_item_through_its_row(self):
        with make_repo(FILES) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "n.txt").write_text("/alive\n/v1/health\nPASSWORD_ITERATIONS\nDefaultBaseURL\nautosave-interval\n")
            code, out = run(repo, "--resolve", str(Path(d, "n.txt")))
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "/alive | src/api/web.rs:%d" % line_of("src/api/web.rs", '#[get("/alive")]'),
            "/v1/health | server/server.go:%d" % line_of("server/server.go", "apiHealthPath  "),
            "PASSWORD_ITERATIONS | src/config.rs:%d" % line_of("src/config.rs", "password_iterations:"),
            "DefaultBaseURL | client/config.go:%d" % line_of("client/config.go", "DefaultBaseURL ="),
            "autosave-interval | lapce-app/src/config/editor.rs:%d" % line_of("lapce-app/src/config/editor.rs", "pub autosave_interval"),
        ])


if __name__ == "__main__":
    unittest.main()
