"""Black-box tests for dot_local/bin/executable_vpn-keepalive.

The real tick runs as a real process. osascript, curl and pgrep are fakes (first on PATH): the fake osascript answers
Viscosity's name/state list and logs every disconnect, connect and notification; the fake curl logs the probe URL and
can fail, or fail only its first N calls (a tunnel that comes back during the re-probe window); the fake pgrep says
whether Viscosity runs. Nothing here calls the real Viscosity or the real network. State and log go to a scratch
XDG_STATE_HOME. Run: python3 -m unittest discover -s tests/vpn-keepalive
"""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "dot_local/bin/executable_vpn-keepalive"
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
echo "alert $VPN_KEEPALIVE_REASON" >> "$FAKE/alert-calls"
if [ -n "${FAKE_ALERT_SLEEP:-}" ]; then sleep "$FAKE_ALERT_SLEEP"; fi
exit "${FAKE_ALERT_CODE:-0}"
"""


class Env:
    def __init__(self, mode="alert", **env):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fake, self.bin, self.state = (self.root / n for n in ("fake", "bin", "state"))
        for d in (self.fake, self.bin, self.state):
            d.mkdir()
        (self.bin / "osascript").write_text(FAKE_OSASCRIPT)
        (self.bin / "curl").write_text(FAKE_CURL)
        (self.bin / "pgrep").write_text(FAKE_PGREP)
        (self.bin / "alert-cmd").write_text(FAKE_ALERT_COMMAND)
        for f in self.bin.iterdir():
            f.chmod(0o755)
        self.env = dict(os.environ,
                        HOME=str(self.root / "home"), FAKE=str(self.fake), XDG_STATE_HOME=str(self.state),
                        PATH="%s:%s" % (self.bin, SYS), FAKE_CONN_STATE="%s, Connected" % CONN,
                        VPN_KEEPALIVE_CONNECTION=CONN, VPN_KEEPALIVE_HOST=HOST, VPN_KEEPALIVE_MODE=mode,
                        VPN_KEEPALIVE_RECONNECT_MIN_SECS="900", VPN_KEEPALIVE_REPROBE_SECS="2",
                        VPN_KEEPALIVE_REPROBE_STEP="1", VPN_KEEPALIVE_DISCONNECT_WAIT="0")
        self.env.update({k: str(v) for k, v in env.items()})
        for k in list(self.env):
            if k.startswith("VPN_KEEPALIVE_") and self.env[k] == "":
                del self.env[k]

    def run(self, **env):
        return subprocess.run([str(SCRIPT)], capture_output=True, text=True, timeout=60,
                              env=dict(self.env, **env))

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
        f = self.state / "vpn-keepalive/log.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def state_json(self):
        return json.loads((self.state / "vpn-keepalive/state.json").read_text())

    def close(self):
        self.tmp.cleanup()


class TickTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_connected_and_reachable_does_nothing(self):
        r = self.env.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["state"], "Connected")
        self.assertTrue(line["probe"]["ok"])
        self.assertEqual(line["probe"]["httpStatus"], "200")
        self.assertLess(line["probe"]["latencyMs"], 20000)
        self.assertEqual(line["action"], "none")
        self.assertEqual(self.env.state_json(), {"failStreak": 0, "episode": None, "lastReconnect": 0, "reconnectFailures": 0})
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
        self.assertEqual(self.env.state_json()["failStreak"], 1)
        self.assertNotIn("display notification", self.env.joined_calls())

    def test_two_failures_alert_once_per_episode_in_alert_mode(self):
        self.env.run(FAKE_CURL_CODE="7")
        r = self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.assertIn("display notification", self.env.joined_calls())
        self.assertEqual(self.env.state_json()["episode"], {"alerted": True})
        # A third stale tick stays quiet: one alert per stale episode.
        self.env.new_calls()
        self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(self.env.lines()[-1]["action"], "none")
        self.assertNotIn("display notification", self.env.joined_calls())
        # The connection is never touched in alert mode.
        self.assertNotIn("disconnect", self.env.joined_calls())

    def test_alert_command_runs_with_the_reason(self):
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7", VPN_KEEPALIVE_ALERT_COMMAND=str(self.env.bin / "alert-cmd"))
        self.assertEqual((self.env.fake / "alert-calls").read_text().splitlines(),
                         ["alert vpn tunnel is not passing traffic"])

    def test_recovery_is_logged_and_a_new_episode_alerts_again(self):
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.env.run()
        self.assertEqual(self.env.lines()[-1]["action"], "recovered")
        self.assertEqual(self.env.state_json(), {"failStreak": 0, "episode": None, "lastReconnect": 0, "reconnectFailures": 0})
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
        self.assertEqual(self.env.state_json(), {"failStreak": 0, "episode": None, "lastReconnect": 0, "reconnectFailures": 0})

    def test_not_connected_does_nothing(self):
        r = self.env.run(FAKE_CONN_STATE="%s, Disconnected" % CONN)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["state"], "Disconnected")
        self.assertEqual(line["action"], "idle")
        self.assertNotIn("curl", self.env.joined_calls())

    def test_unconfigured_ticks_and_exits_clean(self):
        r = self.env.run(VPN_KEEPALIVE_CONNECTION="", VPN_KEEPALIVE_HOST="", VPN_KEEPALIVE_MODE="")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = self.env.lines()[-1]
        self.assertEqual(line["state"], "unconfigured")
        self.assertEqual(line["action"], "idle")
        self.assertEqual(self.env.calls, [])

    def test_a_connection_name_with_a_metacharacter_is_refused(self):
        r = self.env.run(VPN_KEEPALIVE_CONNECTION='Bad"Name')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.env.lines()[-1]["action"], "error")
        self.assertEqual(self.env.calls, [])


class ReconnectTest(unittest.TestCase):
    def setUp(self):
        self.env = Env(mode="reconnect")

    def tearDown(self):
        self.env.close()

    def assertReconnected(self, joined):
        # Two separate osascript calls, matched as whole commands: 'connect "X"' is a substring of
        # 'disconnect "X"', so a substring check would pass with the connect call missing.
        calls = joined.splitlines()
        d = 'osascript -e tell application "Viscosity" to disconnect "%s"' % CONN
        c = 'osascript -e tell application "Viscosity" to connect "%s"' % CONN
        self.assertIn(d, calls)
        self.assertIn(c, calls)
        self.assertLess(calls.index(d), calls.index(c))

    def test_stale_reconnects_then_alerts_when_still_down(self):
        # Two failing probes make the tunnel stale; the reconnect's re-probe still fails, so it alerts.
        self.env.run(FAKE_CURL_CODE="7")
        r = self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertReconnected(self.env.joined_calls())
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.assertIn("display notification", self.env.joined_calls())
        self.assertGreater(self.env.state_json()["lastReconnect"], 0)

    def test_reconnect_recovers_when_the_tunnel_comes_back(self):
        # The two stale probes and the first re-probe fail; the second re-probe answers.
        self.env.run(FAKE_CURL_FAIL_FIRST="3")
        r = self.env.run(FAKE_CURL_FAIL_FIRST="3")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertReconnected(self.env.joined_calls())
        line = self.env.lines()[-1]
        self.assertEqual(line["action"], "reconnected")
        self.assertTrue(line["probe"]["ok"])
        self.assertEqual(self.env.state_json()["failStreak"], 0)
        self.assertIsNone(self.env.state_json()["episode"])
        # The reconnect attempt is kept, so a fresh stale episode right after is still rate limited.
        self.assertGreater(self.env.state_json()["lastReconnect"], 0)
        self.assertNotIn("display notification", self.env.joined_calls())

    def test_reconnect_is_rate_limited(self):
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7")   # stale: reconnects, and alerts because the re-probe fails too
        self.env.new_calls()
        # Still stale, but the 15 minutes are not over: no disconnect or connect, and no second alert.
        r = self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        joined = self.env.joined_calls()
        self.assertNotIn('disconnect "%s"' % CONN, joined)
        self.assertNotIn('connect "%s"' % CONN, joined)
        self.assertNotIn("display notification", joined)
        self.assertEqual(self.env.lines()[-1]["action"], "none")
        # Once the 15 minutes are over, it reconnects again.
        self.env.run(FAKE_CURL_CODE="7", VPN_KEEPALIVE_RECONNECT_MIN_SECS="0")
        self.assertReconnected(self.env.joined_calls())

    def test_a_missing_mode_variable_falls_back_to_reconnect(self):
        # reconnect is the default: a tick run by hand without VPN_KEEPALIVE_MODE reconnects too.
        env = Env(VPN_KEEPALIVE_MODE="")   # the empty value is dropped, so the variable is absent
        try:
            env.run(FAKE_CURL_CODE="7")
            r = env.run(FAKE_CURL_CODE="7")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertReconnected(env.joined_calls())
        finally:
            env.close()

    def test_a_rate_limited_stale_tick_alerts_when_nothing_was_sent_yet(self):
        # An episode that starts inside the 15-minute window after a reconnect still tells the owner.
        self.env.run(FAKE_CURL_CODE="7", VPN_KEEPALIVE_RECONNECT_MIN_SECS="0")
        self.env.run(FAKE_CURL_CODE="7", VPN_KEEPALIVE_RECONNECT_MIN_SECS="0")
        self.env.run(FAKE_CURL_FAIL_FIRST="0")   # the tunnel answers again: the episode ends
        # New episode: two fresh failures, rate limited, never alerted in this episode.
        self.env.new_calls()
        self.env.run(FAKE_CURL_CODE="7")
        self.env.run(FAKE_CURL_CODE="7")
        self.assertEqual(self.env.lines()[-1]["action"], "alert")
        self.assertIn("display notification", self.env.joined_calls())
        self.assertNotIn('disconnect "%s"' % CONN, self.env.joined_calls())

    def test_each_reconnect_that_fails_doubles_the_wait(self):
        # Each reconnect can open the owner's sign-in: after one that did not bring the host back, the
        # next waits 30 minutes, not 15.
        sd = self.env.state / "vpn-keepalive"
        sd.mkdir(parents=True)
        now = int(time.time())
        (sd / "state.json").write_text(json.dumps({"failStreak": 2, "episode": {"alerted": True},
                                                   "lastReconnect": now - 1000, "reconnectFailures": 1}))
        self.env.run(FAKE_CURL_CODE="7")
        self.assertNotIn('to disconnect "%s"' % CONN, self.env.joined_calls())   # 1000 s < 1800 s
        state = json.loads((sd / "state.json").read_text())
        state["lastReconnect"] = now - 2000
        (sd / "state.json").write_text(json.dumps(state))
        self.env.run(FAKE_CURL_CODE="7")
        self.assertReconnected(self.env.joined_calls())                           # 2000 s >= 1800 s
        self.assertEqual(self.env.state_json()["reconnectFailures"], 2)
        line = self.env.lines()[-1]
        self.assertEqual(line["reconnect"], {"disconnect": 0, "connect": 0})

    def test_a_recovery_resets_the_wait(self):
        self.env.run(FAKE_CURL_CODE="7", VPN_KEEPALIVE_RECONNECT_MIN_SECS="0")
        self.env.run(FAKE_CURL_CODE="7", VPN_KEEPALIVE_RECONNECT_MIN_SECS="0")
        self.assertEqual(self.env.state_json()["reconnectFailures"], 1)
        self.env.run()
        self.assertEqual(self.env.state_json()["reconnectFailures"], 0)

    def test_a_slow_alert_command_does_not_lose_the_reconnect_time(self):
        # An alert command past its timeout is a failed alert, not a crash: the reconnect time is kept,
        # so the next tick does not reconnect again, and the tick still logs a line.
        env = Env(mode="reconnect", VPN_KEEPALIVE_ALERT_COMMAND=str(self.env.bin / "alert-cmd"),
                  VPN_KEEPALIVE_ALERT_TIMEOUT="1")
        try:
            (env.bin / "alert-cmd").write_text(FAKE_ALERT_COMMAND)
            (env.bin / "alert-cmd").chmod(0o755)
            env.env["VPN_KEEPALIVE_ALERT_COMMAND"] = str(env.bin / "alert-cmd")
            env.run(FAKE_CURL_CODE="7")
            r = env.run(FAKE_CURL_CODE="7", FAKE_ALERT_SLEEP="5")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(env.lines()[-1]["action"], "alert-failed")
            self.assertGreater(env.state_json()["lastReconnect"], 0)
            env.new_calls()
            env.run(FAKE_CURL_CODE="7")
            self.assertNotIn('to disconnect "%s"' % CONN, env.joined_calls())
        finally:
            env.close()


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

    def test_a_state_file_of_the_wrong_type_is_a_fresh_start(self):
        sd = self.env.state / "vpn-keepalive"
        sd.mkdir(parents=True)
        for bad in ("[]", '"x"', '{"failStreak": "lots", "episode": 3, "lastReconnect": null}'):
            with self.subTest(bad):
                (sd / "state.json").write_text(bad)
                r = self.env.run()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.env.lines()[-1]["action"], "none")


if __name__ == "__main__":
    unittest.main()
