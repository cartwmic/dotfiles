"""The scheduled QMD refresh and qmd on PATH (docs/qmd.md "Scheduled refresh", "qmd on PATH").

Static: the plist, the setting (chezmoi data qmd.refresh) and the load script are rendered from the real source with a throwaway
config and HOME. Behaviour: the runner, the load script and the qmd wrapper run as real processes against fakes (qmd-refresh,
launchctl, uname, the mise shim) in scratch directories. Nothing here calls the real launchctl, qmd or heavy-gate.
"""
import os
import platform
import plistlib
import re
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from test_qmd import REPO

PLIST = REPO / "Library/LaunchAgents/local.qmd-refresh.plist.tmpl"
LOADER = REPO / "run_onchange_after_71_qmd_refresh_launchd.sh.tmpl"
RUNNER = REPO / "dot_local/bin/executable_qmd-refresh-scheduled"
WRAPPER = REPO / "dot_local/bin/executable_qmd"
REFRESH = REPO / "dot_local/bin/executable_qmd-refresh"
DOC = REPO / "docs/qmd.md"
DARWIN = platform.system() == "Darwin"
SYS = "/usr/bin:/bin:/usr/sbin:/sbin"


class Chezmoi:
    """chezmoi against the repo with a minimal config (no hooks), extra local data as YAML lines, and a throwaway HOME."""

    def __init__(self, profile="personal", data=""):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / "Library").mkdir(parents=True)
        self.cfg = Path(self.tmp.name) / "chezmoi.yaml"
        self.set(profile, data)
        self.env = dict(os.environ, HOME=str(self.home))

    def set(self, profile="personal", data=""):
        self.cfg.write_text("data:\n  profile: %s\n%s" % (profile, "".join("  %s\n" % l for l in data.splitlines())))

    def run(self, *args, stdin=None, check=True):
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(self.cfg), "--config-format", "yaml",
                            "--destination", str(self.home), "--no-tty", *args],
                           input=stdin, capture_output=True, text=True, env=self.env, timeout=120)
        if check and r.returncode:
            raise AssertionError("chezmoi %s failed: %s" % (args, r.stderr))
        return r

    def render(self, path, check=True):
        return self.run("execute-template", stdin=path.read_text(), check=check)

    def close(self):
        self.tmp.cleanup()


def render(path, profile="personal", data="", check=True):
    c = Chezmoi(profile, data)
    try:
        r = c.render(path, check=check)
        return r, str(c.home)
    finally:
        c.close()


class SettingTest(unittest.TestCase):
    def plist(self, data="", profile="personal"):
        r, home = render(PLIST, profile, data)
        return r.stdout, home

    def test_default_is_hourly(self):
        out, home = self.plist()
        p = plistlib.loads(out.encode())
        self.assertEqual(p["Label"], "local.qmd-refresh")
        self.assertEqual(p["StartInterval"], 3600)
        self.assertEqual(p["ProgramArguments"], ["/bin/sh", home + "/.local/bin/qmd-refresh-scheduled", "--wait", "3600"])

    def test_override_renders_the_override(self):
        for value, secs in (("120", 7200), ('"90"', 5400), ("15", 900), ("1440", 86400)):
            out, home = self.plist("qmd: {refresh: {intervalMinutes: %s}}" % value)
            p = plistlib.loads(out.encode())
            self.assertEqual(p["StartInterval"], secs, value)
            self.assertEqual(p["ProgramArguments"][-2:], ["--wait", str(secs)], value)

    def test_enabled_true_is_the_default(self):
        (a, ha), (b, hb) = self.plist("qmd: {refresh: {enabled: true}}"), self.plist()
        self.assertEqual(a.replace(ha, "~"), b.replace(hb, "~"))

    def test_off_renders_no_agent(self):
        # An empty template makes chezmoi remove the installed plist (ApplyTest shows it on a scratch HOME).
        self.assertEqual(self.plist("qmd: {refresh: {enabled: false}}")[0], "")
        self.assertEqual(self.plist("qmd: {refresh: {enabled: false, intervalMinutes: 30}}")[0], "")

    def test_a_bad_value_fails_the_render(self):
        # Fail closed: a typo must stop the apply, not schedule something else or nothing silently.
        for data in ("qmd: {refresh: {intervalMinutes: 5}}", "qmd: {refresh: {intervalMinutes: 1441}}",
                     "qmd: {refresh: {intervalMinutes: 0}}", "qmd: {refresh: {intervalMinutes: hourly}}",
                     "qmd: {refresh: {intervalMinutes: 60.5}}", "qmd: {refresh: {intervalMinutes: -60}}",
                     'qmd: {refresh: {enabled: "yes"}}', "qmd: {refresh: {enabled: 1}}"):
            for path in (PLIST, LOADER):
                r, _ = render(path, data=data, check=False)
                self.assertNotEqual(r.returncode, 0, (path.name, data))
                self.assertIn("qmd.refresh.", r.stderr, data)

    def test_the_agent(self):
        out, home = self.plist()
        p = plistlib.loads(out.encode())
        self.assertIs(p["RunAtLoad"], False, "loading it (apply, login) must not start a heavy job")
        self.assertNotIn("Nice", p, "qmd-refresh already runs nice -n 10; launchd's Nice would add to it")
        self.assertNotIn("ProcessType", p)
        self.assertNotIn("KeepAlive", p)
        self.assertNotIn("LowPriorityIO", p)
        self.assertEqual(p["StandardOutPath"], home + "/Library/Logs/qmd-refresh/launchd.log")
        self.assertEqual(p["StandardErrorPath"], p["StandardOutPath"])
        path = p["EnvironmentVariables"]["PATH"].split(":")
        self.assertEqual(path[:2], [home + "/.local/share/mise/shims", home + "/.local/bin"])
        for d in ("/usr/bin", "/bin", "/usr/sbin", "/sbin"):
            self.assertIn(d, path)
        self.assertEqual(sorted(p["EnvironmentVariables"]), ["PATH"])
        self.assertNotIn("reembed", out)
        self.assertNotIn("heavy-gate --", out, "no second gate: qmd-refresh gates itself")

    def test_work_gets_the_same_agent(self):
        a, home_a = self.plist(profile="personal")
        b, home_b = self.plist(profile="axon-work-computer")
        self.assertEqual(a.replace(home_a, "~"), b.replace(home_b, "~"))
        self.assertEqual(self.plist("qmd: {refresh: {enabled: false}}", "axon-work-computer")[0], "")


class ManagedTest(unittest.TestCase):
    def managed(self, profile, data=""):
        c = Chezmoi(profile, data)
        try:
            return set(c.run("managed").stdout.split())
        finally:
            c.close()

    def test_wrapper_and_runner_on_personal_and_work_not_termux(self):
        for profile in ("personal", "axon-work-computer"):
            m = self.managed(profile)
            self.assertIn(".local/bin/qmd", m, profile)
            self.assertIn(".local/bin/qmd-refresh-scheduled", m, profile)
        m = self.managed("termux")
        self.assertEqual([p for p in m if "qmd" in p], [])

    def test_the_agent_and_its_load_script_are_macos_personal_and_work_only(self):
        for profile in ("personal", "axon-work-computer"):
            m = self.managed(profile)
            for p in ("Library/LaunchAgents/local.qmd-refresh.plist", "71_qmd_refresh_launchd.sh"):
                self.assertEqual(p in m, DARWIN, (profile, p))
        m = self.managed("termux")
        self.assertNotIn("Library/LaunchAgents/local.qmd-refresh.plist", m)
        self.assertNotIn("71_qmd_refresh_launchd.sh", m)


@unittest.skipUnless(DARWIN, "the agent is managed on macOS only")
class ApplyTest(unittest.TestCase):
    """chezmoi apply of the LaunchAgents directory only, scripts excluded, into a scratch HOME: no launchctl, no live file."""

    def test_change_the_setting_and_apply_rewrites_or_removes_the_plist(self):
        c = Chezmoi()
        self.addCleanup(c.close)
        agents = c.home / "Library/LaunchAgents"
        plist = agents / "local.qmd-refresh.plist"

        def apply():
            c.run("apply", "--exclude=scripts", str(agents))
            self.assertEqual(c.run("diff", "--exclude=scripts", str(agents)).stdout, "", "chezmoi diff is empty after apply")

        apply()
        self.assertEqual(plistlib.loads(plist.read_bytes())["StartInterval"], 3600)
        c.set(data="qmd: {refresh: {intervalMinutes: 180}}")
        apply()
        self.assertEqual(plistlib.loads(plist.read_bytes())["StartInterval"], 10800)
        c.set(data="qmd: {refresh: {enabled: false}}")
        apply()
        self.assertFalse(plist.exists())
        c.set(data="qmd: {refresh: {intervalMinutes: 3}}")
        r = c.run("apply", "--exclude=scripts", str(agents), check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(plist.exists(), "a bad value writes nothing")
        c.set()
        apply()
        self.assertTrue(plist.exists())
        if Path("/usr/bin/plutil").exists():
            subprocess.run(["/usr/bin/plutil", "-lint", str(plist)], check=True, capture_output=True)


# A stateful launchctl: "loaded" is a file. print says whether it is loaded (113 when not, as the real one); bootout unloads
# unless FAKE_BOOTOUT_STUCK is set; bootstrap loads unless FAKE_BOOTSTRAP_RC is non-zero.
FAKE_LAUNCHCTL = r"""#!/bin/sh
echo "launchctl $*" >> "$FAKE/calls"
case $1 in
  print) [ -f "$FAKE/loaded" ] || exit 113 ;;
  bootout) [ -f "$FAKE/loaded" ] || exit 3; [ -z "${FAKE_BOOTOUT_STUCK:-}" ] || exit 5; rm -f "$FAKE/loaded" ;;
  bootstrap) [ "${FAKE_BOOTSTRAP_RC:-0}" = 0 ] || exit "$FAKE_BOOTSTRAP_RC"; [ ! -f "$FAKE/loaded" ] || exit 5; : > "$FAKE/loaded" ;;
  *) exit 64 ;;
esac
"""


class LoaderTest(unittest.TestCase):
    """The run_onchange script, rendered, then run with a fake launchctl and uname first on PATH."""

    def run_loader(self, data="", installed=True, loaded=False, **env):
        r, home = render(LOADER, data=data)
        script = r.stdout
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        h, fake, bin_ = root / "home", root / "fake", root / "bin"
        for d in (h / "Library/LaunchAgents", fake, bin_):
            d.mkdir(parents=True)
        (bin_ / "launchctl").write_text(FAKE_LAUNCHCTL)
        (bin_ / "uname").write_text("#!/bin/sh\necho Darwin\n")
        for f in bin_.iterdir():
            f.chmod(0o755)
        plist = h / "Library/LaunchAgents/local.qmd-refresh.plist"
        if installed:
            plist.write_text("<plist/>")
        if loaded:
            (fake / "loaded").write_text("")
        p = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, timeout=30,
                           env=dict(env, HOME=str(h), FAKE=str(fake), PATH="%s:%s" % (bin_, SYS)))
        calls = (fake / "calls").read_text().splitlines() if (fake / "calls").exists() else []
        self.loaded = (fake / "loaded").exists()
        return p, [c.split()[1] for c in calls], plist, h, script

    def test_enabled_loads_the_plist(self):
        p, calls, plist, h, _ = self.run_loader()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(calls, ["print", "bootstrap"])
        self.assertTrue(self.loaded)
        self.assertTrue((h / "Library/Logs/qmd-refresh").is_dir(), "launchd needs the log directory before it starts the job")
        self.assertIn("every 60 minutes", p.stdout)

    def test_enabled_and_loaded_reloads_by_label(self):
        uid = os.getuid()
        p, calls, plist, h, _ = self.run_loader(loaded=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(calls, ["print", "bootout", "print", "bootstrap"])
        self.assertTrue(self.loaded)
        calls = (h.parent / "fake/calls").read_text().splitlines()
        self.assertIn("launchctl bootout gui/%d/local.qmd-refresh" % uid, calls)
        self.assertIn("launchctl bootstrap gui/%d %s" % (uid, plist), calls)

    def test_off_unloads_and_removes_and_never_bootstraps(self):
        for loaded, expect in ((True, ["print", "bootout", "print"]), (False, ["print"])):
            p, calls, plist, _, _ = self.run_loader("qmd: {refresh: {enabled: false}}", loaded=loaded)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(calls, expect)
            self.assertFalse(self.loaded)
            self.assertFalse(plist.exists())

    def test_an_unload_that_fails_fails_the_apply_so_it_is_retried(self):
        # chezmoi records a run_onchange script only when it exits 0; a job left running must not be recorded as turned off.
        for data in ("qmd: {refresh: {enabled: false}}", ""):
            p, calls, plist, _, _ = self.run_loader(data, loaded=True, FAKE_BOOTOUT_STUCK="1")
            self.assertNotEqual(p.returncode, 0, data)
            self.assertIn("could not unload", p.stdout)
            self.assertNotIn("bootstrap", calls)
            self.assertTrue(plist.exists(), "the plist stays until the job is really unloaded")

    def test_a_load_that_fails_fails_the_apply(self):
        p, calls, _, _, _ = self.run_loader(FAKE_BOOTSTRAP_RC="5")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("could not load", p.stdout)
        self.assertFalse(self.loaded)

    def test_enabled_without_the_plist_fails_the_apply(self):
        p, calls, _, _, _ = self.run_loader(installed=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("is not installed", p.stdout)
        self.assertNotIn("bootstrap", calls)

    def test_the_rendered_script_changes_with_the_setting_so_chezmoi_reruns_it(self):
        a = render(LOADER)[0].stdout
        b = render(LOADER, data="qmd: {refresh: {intervalMinutes: 120}}")[0].stdout
        c = render(LOADER, data="qmd: {refresh: {enabled: false}}")[0].stdout
        self.assertEqual(len({a, b, c}), 3)
        self.assertIn("# setting: 60\n", a)
        self.assertRegex(a, r"# plist: [0-9a-f]{64}\n")

    def test_only_print_bootout_and_bootstrap(self):
        for data in ("", "qmd: {refresh: {enabled: false}}"):
            s = render(LOADER, data=data)[0].stdout
            self.assertEqual(set(re.findall(r"launchctl (\w+)", s)), {"print", "bootout", "bootstrap"} if data == "" else {"print", "bootout"})
            self.assertNotIn("qmd-refresh --", s)


FAKE_REFRESH = r"""#!/bin/sh
printf '%s\n' "$@" > "$FAKE/args"
echo $$ > "$FAKE/pid"
if [ -n "${FAKE_TERM_WAIT:-}" ]; then
  trap 'echo term >> "$FAKE/signals"; exit 143' TERM
  sleep 30 & wait
fi
[ -z "${FAKE_LEAVE_CHILD:-}" ] || sleep 30 &
cat "$FAKE/out" 2>/dev/null
cat "$FAKE/err" >&2 2>/dev/null
exit "${FAKE_RC:-0}"
"""
# What a real run prints (from qmd-refresh, heavy-gate and qmd 2.8.3, abridged): the job-script echo, escapes, a progress bar,
# the per-chunk truncation warnings.
REAL_ERR = (
    "qmd-refresh: 17:26:37 start: update + embed (waiting up to 3600s for a quiet Mac)\n"
    "[heavy-gate] INFO: allowed; running: sh -c set -e\n"
    '[ "$5" = none ] || "$5"\n'
    '"$1" update\n'
    'QMD_EMBED_CONTEXT_SIZE=$6 QMD_EMBED_PARALLELISM=1 "$1" embed $force --timeout 0\n'
    'if [ "$ok" = 1 ]; then echo "$6" > "$7"; else : > "$4/legacy"; fi sh /x/qmd embed /x/model.gguf\n'
    "\x1b[?25l\u26a0 Batch text truncated to fit embedding context (506 tokens)\n"
    + "\u26a0 Text truncated to fit embedding context (506 tokens)\n" * 3
    + "\r\u2588\u2588\u2588\u2588\u2591\u2591 40%   \r\u2588\u2588\u2588\u2588\u2588\u2588 100%\n\n"
    "\u2713 Done! Embedded 12 chunks from 3 documents in 1s\n"
    "\x1b[?25hqmd-refresh: 17:29:29 done: update + embed\n"
)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake, self.logs = self.root / "fake", self.root / "logs"
        self.fake.mkdir()
        self.bin = self.root / "qmd-refresh"
        self.bin.write_text(FAKE_REFRESH)
        self.bin.chmod(0o755)
        self.env = dict(HOME=str(self.root), PATH=SYS, FAKE=str(self.fake), QMD_REFRESH_BIN=str(self.bin),
                        QMD_REFRESH_LOG_DIR=str(self.logs))

    def popen(self, *args, **env):
        return subprocess.Popen(["/bin/sh", str(RUNNER), *args], env=dict(self.env, **env), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def run_(self, *args, **env):
        p = self.popen(*(args or ("--wait", "3600")), **env)
        self.out, self.err = p.communicate(timeout=60)
        return p.returncode

    @property
    def day(self):
        files = sorted(self.logs.glob("qmd-refresh-*.log"))
        self.assertEqual(len(files), 1, files)
        self.assertRegex(files[0].name, r"^qmd-refresh-\d{4}-\d\d-\d\d\.log$")
        return files[0].read_text()

    def test_one_plain_refresh_with_the_wait_and_nothing_else(self):
        self.assertEqual(self.run_(), 0, self.err)
        self.assertEqual((self.fake / "args").read_text().split(), ["--wait", "3600"], "never --reembed, no other flag")

    def test_a_run_is_one_timestamped_block_without_the_noise(self):
        (self.fake / "err").write_text(REAL_ERR)
        (self.fake / "out").write_text("qmd-export: sessions: 2 written\nIndexed: 0 new, 1 updated, 71 unchanged, 0 removed\n")
        self.assertEqual(self.run_(), 0, self.err)
        log = self.day
        lines = log.splitlines()
        self.assertRegex(lines[0], r"^== \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4} start \(heavy-gate wait up to 3600s\)$")
        self.assertRegex(lines[-1], r"^== \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4} end rc=0 after \d+s$")
        self.assertIn("qmd-export: sessions: 2 written", log)
        self.assertIn("\u2713 Done! Embedded 12 chunks from 3 documents in 1s", log)
        self.assertIn("qmd-refresh: 17:29:29 done: update + embed", log)
        self.assertIn("[heavy-gate] INFO: allowed; running: <the qmd-refresh job>", log)
        self.assertIn('(4 "truncated to fit embedding context" warnings, expected with QMD_EMBED_CONTEXT_SIZE=506)', log)
        for noise in ("\x1b", "\r", "\u2588", "40%", '"$1" update', "QMD_EMBED_PARALLELISM", "\u26a0"):
            self.assertNotIn(noise, log)
        self.assertFalse([l for l in lines if not l.strip()])

    def gate_echo(self, job, args="sh /x/qmd embed /x/model.gguf /x/run none 506 /x/ectx 0 /x/index.sqlite"):
        return ("qmd-refresh: 17:26:37 start: update + embed (waiting up to 3600s for a quiet Mac)\n"
                "[heavy-gate] INFO: allowed; running: sh -c %s %s\n"
                "qmd-export: sessions: 2 written\nIndexed: 0 new, 1 updated, 71 unchanged, 0 removed\n"
                "qmd-refresh: 17:29:29 done: update + embed + cleanup\n" % (job, args))

    def test_the_whole_real_job_script_is_hidden_and_the_output_after_it_kept(self):
        # Built from the job text in qmd-refresh itself, so a longer job can never leak into the log again.
        src = REFRESH.read_text()
        start = src.index("job='") + len("job='")
        end = src.index(": end of the qmd-refresh job'", start) + len(": end of the qmd-refresh job")
        job = src[start:end]
        self.assertGreater(job.count("\n"), 30)
        (self.fake / "err").write_text(self.gate_echo(job, "sh /x/qmd embed /x/m /x/run none 506 /x/ectx 0 /x/index.sqlite 1 /x/last-cleanup /x/index.yml"))
        self.assertEqual(self.run_(), 0, self.err)
        log = self.day
        for line in job.splitlines()[1:]:
            if line.strip() and line.strip() not in ("fi", "esac"):
                self.assertNotIn(line, log)
        for kept in ("[heavy-gate] INFO: allowed; running: <the qmd-refresh job>", "qmd-export: sessions: 2 written",
                     "Indexed: 0 new, 1 updated, 71 unchanged, 0 removed", "done: update + embed + cleanup"):
            self.assertIn(kept, log)

    def test_the_echo_of_a_job_from_before_the_daily_cleanup_is_hidden_too(self):
        (self.fake / "err").write_text(self.gate_echo('set -e\n"$1" update\nif [ "$ok" = 1 ]; then echo "$6" > "$7"; else : > "$4/legacy"; fi'))
        self.assertEqual(self.run_(), 0, self.err)
        log = self.day
        self.assertNotIn('"$1" update', log)
        self.assertIn("qmd-export: sessions: 2 written", log)
        self.assertIn("Indexed: 0 new, 1 updated", log)

    def test_the_noise_filter_keeps_utf8_lines_in_the_c_locale(self):
        # launchd gives the job no LANG: a byte-wise bracket expression would drop every line with a multi-byte character.
        (self.fake / "out").write_text("\u2713 All collections updated.\n")
        self.assertEqual(self.run_(LC_ALL="C"), 0)
        self.assertIn("\u2713 All collections updated.", self.day)

    def test_busy_or_gave_up_is_one_quiet_line(self):
        for err, why in (("qmd-refresh: another refresh is running (lock /s/lock)\n", "another refresh is running (lock /s/lock)"),
                         ("[heavy-gate] WARN: still refused after 3600s; not running: sh -c set -e\nlots\nof\njob\n"
                          "qmd-refresh: 18:00:00 status 75: heavy-gate gave up waiting for a quiet Mac (or the job itself returned 75)\n"
                          "qmd-refresh: 18:00:00 failed with status 75 (last good refresh: x)\n",
                          "18:00:00 status 75: heavy-gate gave up waiting")):
            for f in self.logs.glob("*.log"):
                f.unlink()
            (self.fake / "err").write_text(err)
            self.assertEqual(self.run_(FAKE_RC="75"), 75)
            self.assertEqual(self.out + self.err, "")
            lines = self.day.splitlines()
            self.assertEqual(len(lines), 1, lines)
            self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\dT\S+ skipped rc=75 after \d+s: ")
            self.assertIn(why, lines[0])

    def test_failures_keep_their_status_and_output(self):
        (self.fake / "err").write_text("qmd-refresh: 18:00:00 failed with status 3 (last good refresh: none)\n")
        self.assertEqual(self.run_(FAKE_RC="3"), 3)
        self.assertIn("failed with status 3", self.day)
        self.assertIn("end rc=3 after", self.day)

    def test_a_missing_refresh_is_one_line_and_127(self):
        self.assertEqual(self.run_(QMD_REFRESH_BIN=str(self.root / "nope")), 127)
        self.assertIn("rc=127: %s not found" % (self.root / "nope"), self.day)

    def test_bad_arguments(self):
        for args in ((), ("--wait",), ("--wait", "1h"), ("--reembed",), ("--wait", "60", "--reembed")):
            p = self.popen(*args)
            p.communicate(timeout=30)
            self.assertEqual(p.returncode, 2, args)
        self.assertFalse((self.fake / "args").exists())

    def test_old_day_files_go(self):
        self.logs.mkdir()
        old = self.logs / "qmd-refresh-2020-01-01.log"
        recent = self.logs / "qmd-refresh-2020-01-02.log"
        other = self.logs / "keep-me.txt"
        for f in (old, recent, other):
            f.write_text("x\n")
        t = time.time()
        os.utime(old, (t - 20 * 86400, t - 20 * 86400))
        os.utime(other, (t - 20 * 86400, t - 20 * 86400))
        os.utime(recent, (t - 3 * 86400, t - 3 * 86400))
        self.assertEqual(self.run_(), 0)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists() and other.exists())

    def test_the_day_file_never_passes_the_cap(self):
        # 1.5 MB of output (more than a pipe holds) against a 4000-byte cap: the run still finishes, its output is cut to fit,
        # and later runs add a line only while one fits.
        (self.fake / "out").write_text("".join("line %06d of real output\n" % i for i in range(60000)))
        cap = 4000
        for i in range(12):
            self.assertEqual(self.run_(QMD_REFRESH_LOG_MAX_BYTES=str(cap)), 0)
            self.assertLessEqual(len(self.day.encode()), cap, i)
        log = self.day
        self.assertIn("line 000000 of real output", log)
        self.assertIn("(output cut: the day log is near its size cap)", log)
        self.assertNotIn("line 059999", log)
        self.assertIn("end rc=0 after", log)
        self.assertEqual(self.run_(QMD_REFRESH_LOG_MAX_BYTES=str(cap)), 0)
        self.assertEqual(self.day, log, "a full file gets nothing more")
        (self.fake / "err").write_text("qmd-refresh: another refresh is running (lock /s/lock)\n")
        for i in range(40):
            self.run_(FAKE_RC="75", QMD_REFRESH_LOG_MAX_BYTES=str(cap))
        self.assertLessEqual(len(self.day.encode()), cap)
        self.assertEqual(list(self.logs.glob(".run.*")), [])

    def test_launchd_log_is_emptied_when_over_the_cap(self):
        self.logs.mkdir()
        (self.logs / "launchd.log").write_text("z" * 500)
        self.run_(QMD_REFRESH_LOG_MAX_BYTES="400")
        self.assertEqual((self.logs / "launchd.log").read_text(), "")
        (self.logs / "launchd.log").write_text("small")
        self.run_(QMD_REFRESH_LOG_MAX_BYTES="400")
        self.assertEqual((self.logs / "launchd.log").read_text(), "small")

    def test_term_reaches_qmd_refresh_and_its_status_is_kept(self):
        p = self.popen("--wait", "3600", FAKE_TERM_WAIT="1")
        pidf = self.fake / "pid"
        end = time.time() + 10
        while not pidf.exists() and time.time() < end:
            time.sleep(0.05)
        time.sleep(0.2)
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertEqual((self.fake / "signals").read_text(), "term\n")
        self.assertIn("end rc=143", self.day)
        self.assertEqual(list(self.logs.glob(".run.*")), [], "the temporary files are removed")

    def test_a_process_left_holding_the_output_does_not_hang_the_run(self):
        # The fake leaves "sleep 30" behind with the output pipe open; the run still ends, within the 5 s grace.
        (self.fake / "out").write_text("before\n")
        t = time.time()
        self.assertEqual(self.run_(FAKE_LEAVE_CHILD="1"), 0)
        self.assertLess(time.time() - t, 15)
        self.assertIn("before", self.day)
        self.assertIn("end rc=0", self.day)


class WrapperTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.shims = self.root / "mise/shims"
        self.shims.mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "qmd").write_text(WRAPPER.read_text())
        (self.bin / "qmd").chmod(0o755)
        self.env = dict(HOME=str(self.root), PATH="%s:%s" % (self.bin, SYS), MISE_DATA_DIR=str(self.root / "mise"))

    def shim(self, body):
        (self.shims / "qmd").write_text("#!/bin/sh\n" + body)
        (self.shims / "qmd").chmod(0o755)

    def run_(self, *args, **env):
        return subprocess.run([str(self.bin / "qmd"), *args], env=dict(self.env, **env), capture_output=True, text=True, timeout=20)

    def test_it_runs_the_mise_shim_with_the_arguments_and_status(self):
        self.shim('printf "%s|" "$@"; echo; exit 7\n')
        r = self.run_("search", "two words", "-n", "5")
        self.assertEqual(r.returncode, 7)
        self.assertEqual(r.stdout, "search|two words|-n|5|\n")

    def test_default_shim_dir_is_under_home(self):
        d = self.root / ".local/share/mise/shims"
        d.mkdir(parents=True)
        (d / "qmd").write_text("#!/bin/sh\necho home-shim\n")
        (d / "qmd").chmod(0o755)
        env = dict(self.env)
        del env["MISE_DATA_DIR"]
        r = subprocess.run([str(self.bin / "qmd")], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.stdout, "home-shim\n")

    def test_no_shim_is_127_with_a_hint(self):
        r = self.run_("--version")
        self.assertEqual(r.returncode, 127)
        self.assertIn("mise install", r.stderr)

    def test_a_shim_that_falls_back_to_path_does_not_loop(self):
        # mise's shim searches PATH when qmd is not in the toolset; that finds this wrapper again.
        self.shim('exec qmd "$@"\n')
        r = self.run_("--version")
        self.assertEqual(r.returncode, 127)
        self.assertIn("mise did not resolve qmd", r.stderr)


class DocTest(unittest.TestCase):
    def test_the_knob_logs_and_the_path_fix_are_documented(self):
        d = DOC.read_text()
        for s in ("qmd.refresh.enabled", "qmd.refresh.intervalMinutes", "~/Library/Logs/qmd-refresh", "local.qmd-refresh",
                  "qmd-refresh-scheduled", "~/.local/bin/qmd", "launchctl bootout", "## Scheduled refresh", "## qmd on PATH"):
            self.assertIn(s, d)
        self.assertNotIn("Nothing schedules it", d)
        self.assertNotIn("Nothing schedules it", REFRESH.read_text())

    def test_the_example_config_shows_the_knob(self):
        self.assertIn("intervalMinutes", (REPO / "example.chezmoi.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
