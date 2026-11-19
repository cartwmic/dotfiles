"""Black-box tests for dot_local/bin/executable_session-keepalive.

The real tick runs as a real process. osascript, curl and pgrep are fakes (first on PATH): the fake osascript answers
Viscosity's name/state list and logs every disconnect, connect and notification; the fake curl logs the probe URL and
can fail, or fail only its first N calls (a tunnel that comes back during the re-probe window); the fake pgrep says
whether Viscosity runs. A command check's probe and refresh are scripts the test writes into the fake bin dir and
names in the check config, so the same helpers double as slow, failing, leaking and one-shot variants. Nothing here
calls the real Viscosity or the real network. State and logs go to a scratch XDG_STATE_HOME.
Run: python3 -m unittest discover -s tests/session-keepalive
"""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "dot_local/bin/executable_session-keepalive"
CONN = "Test VPN"
HOST = "vpn.example.com"
SYS = "/usr/bin:/bin:/usr/sbin:/sbin"

FAKE_OSASCRIPT = r"""#!/bin/sh
echo "osascript $*" >> "$FAKE/calls"
case "$*" in
  *"get {name, state} of connections"*) printf '%s\n' "$FAKE_CONN_STATE";;
  *"display notification"*) exit "${FAKE_NOTIFY_CODE:-0}";;
  *) :;;
esac
exit "${FAKE_OSASCRIPT_CODE:-0}"
"""

FAKE_CURL = r"""#!/bin/sh
echo "curl $*" >> "$FAKE/calls"
n=$(cat "$FAKE/curl-calls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$FAKE/curl-calls"
if [ -n "${FAKE_CURL_FAIL_FIRST:-}" ] && [ "$n" -le "$FAKE_CURL_FAIL_FIRST" ]; then exit 7; fi
echo "${FAKE_CURL_STATUS:-200}"
exit "${FAKE_CURL_CODE:-0}"
"""

FAKE_PGREP = r"""#!/bin/sh
echo "pgrep $*" >> "$FAKE/calls"
exit "${FAKE_PGREP_CODE:-0}"
"""

FAKE_ALERT_COMMAND = r"""#!/bin/sh
echo "alert $SESSION_KEEPALIVE_REASON check=$SESSION_KEEPALIVE_CHECK" >> "$FAKE/alert-calls"
echo "ALERT-TOKEN-7q"
echo "ALERT-TOKEN-7q" >&2
if [ -n "${FAKE_ALERT_SLEEP:-}" ]; then sleep "$FAKE_ALERT_SLEEP"; fi
exit "${FAKE_ALERT_CODE:-0}"
"""

FAKE_ORPHAN_SLEEPER = """#!/bin/sh
sleep 30
"""


def viscosity_check(**over):
    check = {"label": CONN, "kind": "viscosity", "mode": "alert", "connection": CONN, "host": HOST}
    check.update(over)
    return check


def command_check(label, probe, **over):
    check = {"label": label, "kind": "command", "mode": "alert", "probe": probe}
    check.update(over)
    return check


def checks_json(*checks):
    return json.dumps(list(checks))


class Env:
    def __init__(self, checks=None, **env):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fake, self.bin, self.state = (self.root / n for n in ("fake", "bin", "state"))
        for d in (self.fake, self.bin, self.state):
            d.mkdir()
        (self.bin / "osascript").write_text(FAKE_OSASCRIPT)
        (self.bin / "curl").write_text(FAKE_CURL)
        (self.bin / "pgrep").write_text(FAKE_PGREP)
        (self.bin / "alert-cmd").write_text(FAKE_ALERT_COMMAND)
        (self.bin / "orphan-sleeper").write_text(FAKE_ORPHAN_SLEEPER)
        for f in self.bin.iterdir():
            f.chmod(0o755)
        self.checks = [viscosity_check()] if checks is None else checks
        self.env = dict(os.environ,
                        HOME=str(self.root / "home"), FAKE=str(self.fake), XDG_STATE_HOME=str(self.state),
                        PATH="%s:%s" % (self.bin, SYS), FAKE_CONN_STATE="%s, Connected" % CONN,
                        SESSION_KEEPALIVE_CHECKS=checks_json(*self.checks),
                        SESSION_KEEPALIVE_REFRESH_MIN_SECS="900", SESSION_KEEPALIVE_REPROBE_SECS="2",
                        SESSION_KEEPALIVE_REPROBE_STEP="1", SESSION_KEEPALIVE_DISCONNECT_WAIT="0")
        self.env.update({k: str(v) for k, v in env.items()})
        for k in list(self.env):
            if k.startswith("SESSION_KEEPALIVE_") and self.env[k] == "":
                del self.env[k]

    def run(self, **env):
        return subprocess.run([str(SCRIPT)], capture_output=True, text=True, timeout=120,
                              env=dict(self.env, **env))

    def write_probe(self, label, fail_first=0, token=None, body=None):
        """A command check's probe as a script: logs to the shared calls file, fails its first
        fail_first calls, then answers. The counter file is named by label, so checks stay independent."""
        lines = ["#!/bin/sh", 'echo "probe %s" >> "$FAKE/calls"' % label]
        if token:
            lines += ["echo %s" % token, "echo %s >&2" % token]
        if body:
            lines.append(body)
        lines += [
            'n=$(cat "$FAKE/%s-count" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$FAKE/%s-count"'
            % (label, label),
            "if [ \"$n\" -le %d ]; then exit 1; fi" % fail_first,
            "exit 0"]
        path = self.bin / ("probe-" + label)
        path.write_text("\n".join(lines) + "\n")
        path.chmod(0o755)
        return str(path)

    def write_refresh(self, label, code=0, token=None, body=None):
        lines = ["#!/bin/sh", 'echo "refresh %s" >> "$FAKE/calls"' % label]
        if token:
            lines += ["echo %s" % token, "echo %s >&2" % token]
        if body:
            lines.append(body)
        lines.append("exit %d" % code)
        path = self.bin / ("refresh-" + label)
        path.write_text("\n".join(lines) + "\n")
        path.chmod(0o755)
        return str(path)

    @property
    def calls(self):
        f = self.fake / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def new_calls(self):
        f = self.fake / "calls"
        if f.exists():
            f.unlink()
        return self.calls

    def joined_calls(self):
        return "\n".join(self.calls)

    def lines(self):
        f = self.state / "session-keepalive/log.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def log_text(self):
        f = self.state / "session-keepalive/log.jsonl"
        return f.read_text() if f.exists() else ""

    def check_state(self, label):
        return json.loads((self.state / "session-keepalive/state" / (label + ".json")).read_text())

    def seed(self, label, **fields):
        d = self.state / "session-keepalive" / "state"
        d.mkdir(parents=True, exist_ok=True)
        (d / (label + ".json")).write_text(json.dumps(fields))

    def count(self, label):
        f = self.fake / ("%s-count" % label)
        return int(f.read_text()) if f.exists() else 0

    def close(self):
        self.tmp.cleanup()


class TickTest(unittest.TestCase):
    """One viscosity check in alert mode: the reviewed behaviour of #613, kept."""
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_the_tunnel_probe_tests_reachability_without_verifying_the_certificate(self):
        # A host behind a private certificate authority must not read as stale: the probe sends nothing
        # and reads nothing, so it skips certificate checks.
        self.env.run()
        probes = [c for c in self.env.calls if c.startswith("curl ")]
        self.assertTrue(probes)
        for c in probes:
            self.assertIn("--insecure", c.split())

    def test_connected_and_reachable_does_nothing(self):
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["check"], CONN)
        self.assertEqual(line["kind"], "viscosity")
        self.assertEqual(line["state"], "Connected")
        self.assertTrue(line["probe"]["ok"])
        self.assertEqual(line["probe"]["httpStatus"], "200")
        self.assertLess(line["probe"]["latencyMs"], 20000)
        self.assertEqual(line["action"], "none")
        state = self.env.check_state(CONN)
        self.assertEqual(state["failStreak"], 0)
        self.assertIsNone(state["episode"])
        self.assertGreater(state["lastRunStart"], 0)
        joined = self.env.joined_calls()
        self.assertNotIn("disconnect", joined)
        self.assertNotIn("connect ", joined)
        self.assertNotIn("display notification", joined)

    def test_one_failure_waits_for_a_second(self):
        r = self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertFalse(line["probe"]["ok"])
        self.assertEqual(line["action"], "none")
        self.assertEqual(self.env.check_state(CONN)["failStreak"], 1)
        self.assertNotIn("display notification", self.env.joined_calls())

    def test_two_failures_alert_once_per_episode_in_alert_mode(self):
        self.env.run(FAKE_CURL_CODE="7")
        r = self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.assertIn("display notification", self.env.joined_calls())
        self.assertTrue(self.env.check_state(CONN)["episode"]["alerted"])
        # A third stale tick stays quiet: one alert per stale episode.
        self.env.new_calls()
        self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(self.env.lines()[-1]["action"], "none")
        self.assertNotIn("display notification", self.env.joined_calls())
        # The connection is never touched in alert mode.
        self.assertNotIn("disconnect", self.env.joined_calls())

    def test_alert_command_runs_with_the_reason_and_the_check(self):
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7",
                     **{"SESSION_KEEPALIVE_CHECKS": checks_json(viscosity_check(alertCommand=str(self.env.bin / "alert-cmd")))})
        self.assertEqual((self.env.fake / "alert-calls").read_text().splitlines(),
                         ["alert vpn tunnel is not passing traffic check=%s" % CONN])

    def test_recovery_is_logged_and_a_new_episode_alerts_again(self):
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.env.run()
        self.assertEqual(self.env.lines()[-1]["action"], "recovered")
        state = self.env.check_state(CONN)
        self.assertEqual(state["failStreak"], 0)
        self.assertIsNone(state["episode"])
        # A fresh stale episode alerts again.
        self.env.new_calls()
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.assertEqual(self.env.joined_calls().count("display notification"), 1)

    def test_viscosity_not_running_does_nothing(self):
        r = self.env.run(FAKE_PGREP_CODE="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["state"], "down")
        self.assertEqual(line["action"], "idle")
        self.assertIsNone(line["probe"])
        joined = self.env.joined_calls()
        self.assertNotIn("get {name, state}", joined)
        self.assertNotIn("curl", joined)
        state = self.env.check_state(CONN)
        self.assertEqual(state["failStreak"], 0)
        self.assertIsNone(state["episode"])

    def test_not_connected_does_nothing(self):
        r = self.env.run(FAKE_CONN_STATE="%s, Disconnected" % CONN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["state"], "Disconnected")
        self.assertEqual(line["action"], "idle")
        self.assertNotIn("curl", self.env.joined_calls())

    def test_unconfigured_ticks_and_exits_clean(self):
        r = self.env.run(SESSION_KEEPALIVE_CHECKS="")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["state"], "unconfigured")
        self.assertEqual(line["action"], "idle")
        self.assertEqual(self.env.calls, [])

    def test_a_check_list_that_is_not_json_is_an_error_line(self):
        r = self.env.run(SESSION_KEEPALIVE_CHECKS="{oops")
        self.assertEqual(r.returncode, 1)
        line = self.env.lines()[-1]
        self.assertEqual(line["action"], "error")
        self.assertEqual(self.env.calls, [])

    def test_a_connection_name_with_a_metacharacter_is_refused(self):
        r = self.env.run(**{"SESSION_KEEPALIVE_CHECKS": checks_json(viscosity_check(connection='Bad"Name'))})
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.env.lines()[-1]["action"], "error")
        self.assertEqual(self.env.calls, [])


class RefreshTest(unittest.TestCase):
    """One viscosity check in refresh mode: the reviewed reconnect machinery of #613, kept."""
    def setUp(self):
        self.env = Env(checks=[viscosity_check(mode="refresh")])

    def tearDown(self):
        self.env.close()

    def assertRefreshed(self, joined):
        # Two separate osascript calls, matched as whole commands: 'connect "X"' is a substring of
        # 'disconnect "X"', so a substring check would pass with the connect call missing.
        calls = joined.splitlines()
        d = 'osascript -e tell application "Viscosity" to disconnect "%s"' % CONN
        c = 'osascript -e tell application "Viscosity" to connect "%s"' % CONN
        self.assertIn(d, calls)
        self.assertIn(c, calls)
        self.assertLess(calls.index(d), calls.index(c))

    def test_stale_refreshes_then_alerts_when_still_down(self):
        # Two failing probes make the tunnel stale; the refresh's re-probe still fails, so it alerts.
        self.env.run(FAKE_CURL_CODE="7")
        r = self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRefreshed(self.env.joined_calls())
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.assertIn("display notification", self.env.joined_calls())
        self.assertGreater(self.env.check_state(CONN)["lastRefresh"], 0)

    def test_refresh_recovers_when_the_tunnel_comes_back(self):
        # The two stale probes and the first re-probe fail; the second re-probe answers.
        self.env.run(FAKE_CURL_FAIL_FIRST="3")
        r = self.env.run(FAKE_CURL_FAIL_FIRST="3")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRefreshed(self.env.joined_calls())
        line = self.env.lines()[-1]
        self.assertEqual(line["action"], "refreshed")
        self.assertTrue(line["probe"]["ok"])
        self.assertEqual(self.env.check_state(CONN)["failStreak"], 0)
        self.assertIsNone(self.env.check_state(CONN)["episode"])
        # The refresh attempt is kept, so a fresh stale episode right after is still rate limited.
        self.assertGreater(self.env.check_state(CONN)["lastRefresh"], 0)
        self.assertNotIn("display notification", self.env.joined_calls())

    def test_refresh_is_rate_limited(self):
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7")   # stale: refreshes, and alerts because the re-probe fails too
        self.env.new_calls()
        # Still stale, but the 15 minutes are not over: no disconnect or connect, and no second alert.
        r = self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        joined = self.env.joined_calls()
        self.assertNotIn('disconnect "%s"' % CONN, joined)
        self.assertNotIn('connect "%s"' % CONN, joined)
        self.assertNotIn("display notification", joined)
        self.assertEqual(self.env.lines()[-1]["action"], "none")
        # Once the 15 minutes are over, it refreshes again.
        self.env.run(FAKE_CURL_CODE="7", SESSION_KEEPALIVE_REFRESH_MIN_SECS="0")
        self.assertRefreshed(self.env.joined_calls())

    def test_a_check_without_a_mode_defaults_to_alert(self):
        # alert is the default for every kind: refresh is always explicit in the data.
        env = Env(checks=[viscosity_check()])   # no mode key at all
        try:
            env.run(FAKE_CURL_CODE="7")
            r = env.run(FAKE_CURL_CODE="7")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(env.lines()[-1]["action"], "alert")
            self.assertNotIn('to disconnect', env.joined_calls())
        finally:
            env.close()

    def test_a_rate_limited_stale_tick_alerts_when_nothing_was_sent_yet(self):
        # An episode that starts inside the 15-minute window after a refresh still tells the owner.
        self.env.run(FAKE_CURL_CODE="7", SESSION_KEEPALIVE_REFRESH_MIN_SECS="0")
        self.env.run(FAKE_CURL_CODE="7", SESSION_KEEPALIVE_REFRESH_MIN_SECS="0")
        self.env.run(FAKE_CURL_FAIL_FIRST="0")   # the tunnel answers again: the episode ends
        # New episode: two fresh failures, rate limited, never alerted in this episode.
        self.env.new_calls()
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.assertIn("display notification", self.env.joined_calls())
        self.assertNotIn('disconnect "%s"' % CONN, self.env.joined_calls())

    def test_each_refresh_that_fails_doubles_the_wait(self):
        # Each refresh can open the owner's sign-in: after one that did not bring the host back, the
        # next waits 30 minutes, not 15.
        now = int(time.time())
        self.env.seed(CONN, lastRunStart=now, failStreak=2, episode={"alerted": True},
                      lastRefresh=now - 1000, refreshFailures=1)
        self.env.run(FAKE_CURL_CODE="7")
        self.assertNotIn('to disconnect "%s"' % CONN, self.env.joined_calls())   # 1000 s < 1800 s
        self.env.seed(CONN, lastRunStart=now, failStreak=2, episode={"alerted": True},
                      lastRefresh=now - 2000, refreshFailures=1)
        self.env.run(FAKE_CURL_CODE="7")
        self.assertRefreshed(self.env.joined_calls())                           # 2000 s >= 1800 s
        self.assertEqual(self.env.check_state(CONN)["refreshFailures"], 2)
        self.assertEqual(self.env.lines()[-1]["refresh"], {"disconnect": 0, "connect": 0})

    def test_a_recovery_resets_the_wait(self):
        self.env.run(FAKE_CURL_CODE="7", SESSION_KEEPALIVE_REFRESH_MIN_SECS="0")
        self.env.run(FAKE_CURL_CODE="7", SESSION_KEEPALIVE_REFRESH_MIN_SECS="0")
        self.assertEqual(self.env.check_state(CONN)["refreshFailures"], 1)
        self.env.run()
        self.assertEqual(self.env.check_state(CONN)["refreshFailures"], 0)

    def test_a_slow_alert_command_does_not_lose_the_refresh_time(self):
        # An alert command past its timeout is a failed alert, not a crash: the refresh time is kept,
        # so the next tick does not refresh again, and the tick still logs a line.
        env = Env(checks=[], SESSION_KEEPALIVE_ALERT_TIMEOUT="1")
        try:
            env.env["SESSION_KEEPALIVE_CHECKS"] = checks_json(
                viscosity_check(mode="refresh", alertCommand=str(env.bin / "alert-cmd")))
            env.run(FAKE_CURL_CODE="7")
            r = env.run(FAKE_CURL_CODE="7", FAKE_ALERT_SLEEP="5")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(env.lines()[-1]["action"], "alert-failed")
            self.assertGreater(env.check_state(CONN)["lastRefresh"], 0)
            env.new_calls()
            env.run(FAKE_CURL_CODE="7")
            self.assertNotIn('to disconnect "%s"' % CONN, env.joined_calls())
        finally:
            env.close()

    def test_a_refresh_that_works_resets_the_wait(self):
        now = int(time.time())
        self.env.seed(CONN, lastRunStart=now, failStreak=2, episode={"alerted": True},
                      lastRefresh=0, refreshFailures=3)
        self.env.run(FAKE_CURL_FAIL_FIRST="2")   # the stale probe and the first re-probe fail, then it answers
        self.assertEqual(self.env.lines()[-1]["action"], "refreshed")
        self.assertEqual(self.env.check_state(CONN)["refreshFailures"], 0)

    def test_the_wait_is_capped_at_one_hour(self):
        # Ten failed refreshes in a row would be 15 min x 1024 without a cap; the cap is 1 hour.
        now = int(time.time())
        self.env.seed(CONN, lastRunStart=now, failStreak=2, episode={"alerted": True},
                      lastRefresh=now - 3500, refreshFailures=10)
        self.env.run(FAKE_CURL_CODE="7")
        self.assertNotIn('to disconnect "%s"' % CONN, self.env.joined_calls())   # 3500 s < 3600 s
        self.env.seed(CONN, lastRunStart=now, failStreak=2, episode={"alerted": True},
                      lastRefresh=now - 3700, refreshFailures=10)
        self.env.run(FAKE_CURL_CODE="7")
        self.assertRefreshed(self.env.joined_calls())                           # 3700 s >= 3600 s


class AlertTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_a_notification_that_fails_is_recorded_and_retried(self):
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7", FAKE_NOTIFY_CODE="1")
        self.assertEqual(self.env.lines()[-1]["action"], "alert-failed")
        self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(self.env.lines()[-1]["action"], "none")   # once per episode after a real alert

    def test_only_the_part_of_an_alert_that_failed_is_retried(self):
        # The notification works, the alert command fails: the next tick reruns the command only, so a
        # pager-style command does not page twice for one shown notification, nor the reverse.
        env = Env(checks=[])
        try:
            env.env["SESSION_KEEPALIVE_CHECKS"] = checks_json(
                viscosity_check(alertCommand=str(env.bin / "alert-cmd")))
            env.run(FAKE_CURL_CODE="7")
            env.run(FAKE_CURL_CODE="7", FAKE_ALERT_CODE="1")
            self.assertEqual(env.lines()[-1]["action"], "alert-failed")
            self.assertEqual(env.joined_calls().count("display notification"), 1)
            env.run(FAKE_CURL_CODE="7")
            self.assertEqual(env.lines()[-1]["action"], "alert")
            self.assertEqual(env.joined_calls().count("display notification"), 1)   # not shown again
            self.assertEqual(len((env.fake / "alert-calls").read_text().splitlines()), 2)
        finally:
            env.close()

    def test_a_state_file_of_the_wrong_type_is_a_fresh_start(self):
        for bad in ("[]", '"x"', '{"failStreak": "lots", "episode": 3, "lastRefresh": null}'):
            with self.subTest(bad):
                self.env.seed(CONN)   # create the directory
                (self.env.state / "session-keepalive/state" / (CONN + ".json")).write_text(bad)
                r = self.env.run()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.env.lines()[-1]["action"], "none")


class CommandCheckTest(unittest.TestCase):
    def setUp(self):
        self.env = Env(checks=[])

    def tearDown(self):
        self.env.close()

    def configure(self, *checks, **env):
        self.env.env["SESSION_KEEPALIVE_CHECKS"] = checks_json(*checks)
        self.env.env.update({k: str(v) for k, v in env.items()})

    def test_a_healthy_command_probe_does_nothing(self):
        probe = self.env.write_probe("aws")
        self.configure(command_check("aws", probe))
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["check"], "aws")
        self.assertEqual(line["kind"], "command")
        self.assertTrue(line["probe"]["ok"])
        self.assertEqual(line["probe"]["exitCode"], 0)
        self.assertEqual(line["action"], "none")

    def test_two_failures_alert_in_alert_mode(self):
        probe = self.env.write_probe("aws", fail_first=99)
        self.configure(command_check("aws", probe))
        self.env.run()
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.assertIn("display notification", self.env.joined_calls())

    def test_refresh_mode_runs_the_refresh_command_then_reprobes(self):
        # The probe fails twice; the refresh runs; the immediate re-probe answers: refreshed.
        probe = self.env.write_probe("aws", fail_first=2)
        refresh = self.env.write_refresh("aws")
        self.configure(command_check("aws", probe, mode="refresh", refresh=refresh))
        self.env.run()
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["action"], "refreshed")
        self.assertEqual(line["refresh"], {"exitCode": 0})
        self.assertTrue(line["probe"]["ok"])
        self.assertEqual(self.env.check_state("aws")["failStreak"], 0)
        self.assertEqual(self.env.count("aws"), 3)   # two stale probes, then the re-probe

    def test_a_refresh_that_fails_alerts_in_the_same_tick(self):
        probe = self.env.write_probe("aws", fail_first=99)
        refresh = self.env.write_refresh("aws", code=3)
        self.configure(command_check("aws", probe, mode="refresh", refresh=refresh))
        self.env.run()
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["action"], "alert")
        self.assertEqual(line["refresh"], {"exitCode": 3})
        self.assertEqual(self.env.check_state("aws")["refreshFailures"], 1)

    def test_mode_refresh_without_a_refresh_command_is_an_error(self):
        probe = self.env.write_probe("aws")
        self.configure(command_check("aws", probe, mode="refresh"))
        r = self.env.run()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.env.lines()[-1]["action"], "error")
        self.assertEqual(self.env.calls, [])

    def test_a_timed_out_probe_is_exit_124_and_its_group_is_killed(self):
        # R4-N2: the probe's whole process group gets SIGTERM, then SIGKILL, so a child that sleeps
        # past the timeout does not outlive the tick.
        probe = self.env.write_probe("aws", body="orphan-sleeper & wait")
        self.configure(command_check("aws", probe, probeTimeoutSeconds=1))
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["probe"]["exitCode"], 124)
        left = subprocess.run(["pgrep", "-f", "orphan-sleeper"], capture_output=True, text=True)
        self.assertNotEqual(left.returncode, 0, left.stdout)

    def test_a_backgrounded_child_holding_stdout_is_bounded(self):
        # R5-N8: the probe exits 0 but leaves a child holding its stdout pipe. The timeout bounds the
        # whole call including output collection, the group kill reaps the child, and nothing leaks.
        probe = self.env.write_probe("aws", token="STDOUT-TOKEN-5z", body="orphan-sleeper & exit 0")
        self.configure(command_check("aws", probe, probeTimeoutSeconds=1))
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["probe"]["exitCode"], 124)
        self.assertNotIn("STDOUT-TOKEN-5z", self.env.log_text())
        self.assertNotIn("STDOUT-TOKEN-5z", r.stdout + r.stderr)
        left = subprocess.run(["pgrep", "-f", "orphan-sleeper"], capture_output=True, text=True)
        self.assertNotEqual(left.returncode, 0, left.stdout)

    def test_the_refresh_timeout_is_exit_124(self):
        probe = self.env.write_probe("aws", fail_first=99)
        refresh = self.env.write_refresh("aws", body="sleep 5")
        self.configure(command_check("aws", probe, mode="refresh", refresh=refresh,
                                     refreshTimeoutSeconds=1))
        self.env.run()
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["refresh"], {"exitCode": 124})
        self.assertEqual(line["action"], "alert")

    def test_children_do_not_see_the_check_list(self):
        # R5-N6: SESSION_KEEPALIVE_CHECKS is config for the tick alone; the alert command gets
        # SESSION_KEEPALIVE_REASON and SESSION_KEEPALIVE_CHECK instead.
        probe = self.env.write_probe("aws", fail_first=99, body='env > "$FAKE/probe-env"')
        alert = self.env.bin / "alert-env-cmd"
        alert.write_text('#!/bin/sh\nenv > "$FAKE/alert-env"\n')
        alert.chmod(0o755)
        self.configure(command_check("aws", probe, alertCommand=str(alert)))
        self.env.run()
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        probe_env = (self.env.fake / "probe-env").read_text()
        alert_env = (self.env.fake / "alert-env").read_text()
        self.assertNotIn("SESSION_KEEPALIVE_CHECKS", probe_env)
        self.assertNotIn("SESSION_KEEPALIVE_CHECKS", alert_env)
        self.assertIn("SESSION_KEEPALIVE_CHECK=aws", alert_env)
        self.assertIn("SESSION_KEEPALIVE_REASON=session check failing", alert_env)


class IntervalTest(unittest.TestCase):
    def setUp(self):
        self.env = Env(checks=[])

    def tearDown(self):
        self.env.close()

    def configure(self, *checks):
        self.env.env["SESSION_KEEPALIVE_CHECKS"] = checks_json(*checks)

    def test_a_check_without_an_interval_runs_on_consecutive_ticks(self):
        # R4-B1: no lastRun gate at all, even when an earlier check takes most of the interval.
        slow = self.env.write_probe("slow", body="sleep 1")
        fast = self.env.write_probe("fast")
        self.configure(command_check("slow", slow), command_check("fast", fast))
        self.env.run()
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.count("fast"), 2)

    def test_an_interval_check_is_skipped_until_its_interval_elapses(self):
        # R5-N1: the gate is tickStart - lastRunStart >= intervalSeconds - 10, a fixed 10 s of slack.
        probe = self.env.write_probe("aws")
        self.configure(command_check("aws", probe, intervalSeconds=300))
        now = int(time.time())
        self.env.seed("aws", lastRunStart=now - 240, failStreak=0, episode=None,
                      lastRefresh=0, refreshFailures=0)
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["action"], "skipped")
        self.assertEqual(self.env.count("aws"), 0)
        # 290 s is exactly interval - slack: due.
        self.env.seed("aws", lastRunStart=now - 290, failStreak=0, episode=None,
                      lastRefresh=0, refreshFailures=0)
        self.env.run()
        self.assertEqual(self.env.lines()[-1]["action"], "none")
        self.assertEqual(self.env.count("aws"), 1)

    def test_a_300s_interval_on_a_120s_tick_runs_every_360s(self):
        # R5-N1, exact ticks: with a 120 s tick, a 300 s interval check is skipped at +120 s and
        # +240 s (both under 290 s) and runs at +360 s - never more often than its interval.
        probe = self.env.write_probe("aws")
        self.configure(command_check("aws", probe, intervalSeconds=300))
        now = int(time.time())
        for elapsed in (120, 240):
            self.env.seed("aws", lastRunStart=now - elapsed, failStreak=0, episode=None,
                          lastRefresh=0, refreshFailures=0)
            self.env.run()
            self.assertEqual(self.env.lines()[-1]["action"], "skipped", elapsed)
        self.env.seed("aws", lastRunStart=now - 360, failStreak=0, episode=None,
                      lastRefresh=0, refreshFailures=0)
        self.env.run()
        self.assertEqual(self.env.lines()[-1]["action"], "none")
        self.assertEqual(self.env.count("aws"), 1)

    def test_a_clock_moved_back_makes_the_check_due(self):
        # R5-N2: tickStart < lastRunStart (the clock moved back) is due now, not blocked.
        probe = self.env.write_probe("aws")
        self.configure(command_check("aws", probe, intervalSeconds=300))
        now = int(time.time())
        self.env.seed("aws", lastRunStart=now + 3600, failStreak=0, episode=None,
                      lastRefresh=0, refreshFailures=0)
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["action"], "none")
        self.assertEqual(self.env.count("aws"), 1)

    def test_a_check_that_just_ran_is_skipped_on_the_next_tick(self):
        probe = self.env.write_probe("aws")
        self.configure(command_check("aws", probe, intervalSeconds=300))
        self.env.run()
        self.assertEqual(self.env.lines()[-1]["action"], "none")
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["action"], "skipped")
        self.assertEqual(self.env.count("aws"), 1)


class MultiCheckTest(unittest.TestCase):
    def setUp(self):
        self.env = Env(checks=[])

    def tearDown(self):
        self.env.close()

    def configure(self, *checks):
        self.env.env["SESSION_KEEPALIVE_CHECKS"] = checks_json(*checks)

    def test_checks_run_serially_viscosity_first(self):
        # The command check is first in the data, but the viscosity check still probes first.
        probe = self.env.write_probe("aws")
        self.configure(command_check("aws", probe), viscosity_check())
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.env.calls
        osascript_i = next(i for i, c in enumerate(calls) if "get {name, state}" in c)
        cmd_i = next(i for i, c in enumerate(calls) if c.startswith("probe aws"))
        self.assertLess(osascript_i, cmd_i)

    def test_two_checks_keep_independent_streaks_and_episodes(self):
        bad = self.env.write_probe("bad", fail_first=99)
        good = self.env.write_probe("good")
        self.configure(command_check("bad", bad), command_check("good", good))
        self.env.run()
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        actions = {line["check"]: line["action"] for line in self.env.lines()[-2:]}
        self.assertEqual(actions, {"bad": "alert", "good": "none"})
        self.assertTrue(self.env.check_state("bad")["episode"]["alerted"])
        self.assertIsNone(self.env.check_state("good")["episode"])

    def test_one_corrupt_state_file_is_a_fresh_start_for_that_check_only(self):
        bad = self.env.write_probe("bad", fail_first=99)
        good = self.env.write_probe("good", fail_first=99)
        self.configure(command_check("bad", bad), command_check("good", good))
        self.env.run()   # both streaks at 1
        self.env.seed("bad")   # replaced by a list below
        (self.env.state / "session-keepalive/state" / "bad.json").write_text("[]")
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        actions = {line["check"]: line["action"] for line in self.env.lines()[-2:]}
        # bad starts over (one failure waits); good keeps its streak and alerts.
        self.assertEqual(actions, {"bad": "none", "good": "alert"})
        self.assertEqual(self.env.check_state("bad")["failStreak"], 1)


class LeakTest(unittest.TestCase):
    """R4-N4 and R5-N5: no token a helper prints, and no command text, reaches log.jsonl or the
    tick's stdout/stderr (what launchd.log catches)."""
    def setUp(self):
        self.env = Env(checks=[])

    def tearDown(self):
        self.env.close()

    def configure(self, *checks):
        self.env.env["SESSION_KEEPALIVE_CHECKS"] = checks_json(*checks)

    def assert_leak_free(self, r, *secrets):
        text = self.env.log_text() + r.stdout + r.stderr
        for secret in secrets:
            self.assertNotIn(secret, text)

    def test_no_token_or_command_text_reaches_the_logs(self):
        probe = self.env.write_probe("aws", fail_first=99, token="PROBE-TOKEN-7q")
        refresh = self.env.write_refresh("aws", code=1, token="REFRESH-TOKEN-7q")
        self.configure(command_check("aws", probe, mode="refresh", refresh=refresh,
                                     alertCommand=str(self.env.bin / "alert-cmd")))
        self.env.run()
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.assert_leak_free(r, "PROBE-TOKEN-7q", "REFRESH-TOKEN-7q", "ALERT-TOKEN-7q",
                              "probe-aws", "refresh-aws")

    def test_a_timed_out_probe_leaks_nothing(self):
        # R5-N5: the timeout path must not carry the command (a raw TimeoutExpired would).
        probe = self.env.write_probe("aws", token="TIMEOUT-TOKEN-5z", body="sleep 5")
        self.configure(command_check("aws", probe, probeTimeoutSeconds=1))
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["probe"]["exitCode"], 124)
        self.assert_leak_free(r, "TIMEOUT-TOKEN-5z", "sleep 5", "probe-aws")

    def test_the_unexpected_error_line_carries_no_command(self):
        # R5-N5: the error log line (a crash inside the tick) must not carry the command either.
        probe = self.env.write_probe("aws")
        self.configure(command_check("aws", probe))
        state_file = self.env.state / "session-keepalive/state" / "aws.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.mkdir()   # a directory: saving the state raises, the tick logs an error line
        r = self.env.run()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.env.lines()[-1]["action"], "error")
        self.assert_leak_free(r, "probe-aws")
        self.assertEqual(self.env.calls, [])   # the probe never ran


if __name__ == "__main__":
    unittest.main()
